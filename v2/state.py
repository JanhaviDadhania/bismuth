"""Runtime state — §6. Tiered on purpose: what breaks if you delete it?

Tier 1 (`state.json`)  authoritative and small. Losing any of it loses work.
Tier 2 (`tasks.json`, `subagents.json`)  derived; folded from the trace at
       boot; deletable without loss.
Tier 3  Popen handles, the semaphore, sockets. Dies with the process — which
       is exactly what boot reconciliation relies on being able to detect.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
import uuid
from contextlib import contextmanager
from typing import Any

from . import config as cfg


def default_state() -> dict:
    return {
        "offset": 0,             # Telegram getUpdates offset
        "processed_ids": [],     # dedup ledger on update_id
        "turn_queue": [],        # notes AND sub-agent results, in arrival order
        "session": None,         # {id, started_at, window_size, tokens}
        "pending_reset": None,   # deferred session reset (§4.5)
        "retry": [],             # visible retry queue — never a silent drop
        # {name: {last_fired, last_fired_at, overdue_flagged}} — written in the
        # SAME mutate() block as the schedule's enqueue, which is the whole
        # reason it lives here and not in the schedule's frontmatter. Tier 1 but
        # tiny: losing it costs one duplicate run, never lost work.
        "schedules": {},
    }


PROCESSED_IDS_KEEP = 5000


@contextmanager
def _locked():
    cfg.ensure_dirs()
    with open(cfg.STATE_LOCK, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def read() -> dict:
    if not cfg.STATE_FILE.exists():
        return default_state()
    try:
        data = json.loads(cfg.STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return default_state()
    base = default_state()
    base.update(data if isinstance(data, dict) else {})
    return base


def write(state: dict) -> None:
    """Atomic. State is always written BEFORE the thing it records."""
    cfg.ensure_dirs()
    ids = state.get("processed_ids") or []
    if len(ids) > PROCESSED_IDS_KEEP:
        state["processed_ids"] = ids[-PROCESSED_IDS_KEEP:]
    tmp = cfg.STATE_TMP
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(cfg.STATE_FILE)


@contextmanager
def mutate():
    """Read-modify-write under the state lock.

        with state.mutate() as s:
            s["offset"] = 12
    """
    with _locked():
        s = read()
        yield s
        write(s)


# ─── the turn queue — the one piece of state with no rebuild path ────────────

def prepare_turn(item: dict) -> dict:
    """Stamp a turn input, without enqueueing it.

    Split out so a caller that must append to `turn_queue` and change something
    else in the SAME `mutate()` block can do so — `mutate()` cannot nest
    (a second `flock` on a fresh fd for the same file would deadlock), and
    `schedules.tick()` needs exactly that atomicity: the enqueue and the
    `last_fired` mark are one write or the run is either lost or duplicated.
    """
    item = dict(item)
    item.setdefault("queued_at", time.time())
    item.setdefault("item_id", uuid.uuid4().hex[:12])
    return item


def enqueue_turn(item: dict) -> None:
    """Durably append one turn input. For sub-agent results this MUST happen
    before the sub-agent's process is reaped: the write is the commit point
    (§6). Lose this and a finished worker's result never reaches the agent and
    its task hangs in `working` forever."""
    with mutate() as s:
        s["turn_queue"].append(prepare_turn(item))


def dequeue_turn() -> dict | None:
    """Pop the oldest turn input. One queue, one turn at a time, whichever the
    source (§4.8)."""
    with mutate() as s:
        queue = s.get("turn_queue") or []
        if not queue:
            return None
        return queue.pop(0)


def queue_depth() -> int:
    return len(read().get("turn_queue") or [])


# ─── dedup ledger ────────────────────────────────────────────────────────────

def already_processed(update_id: int) -> bool:
    return update_id in set(read().get("processed_ids") or [])


def mark_processed(update_id: int) -> None:
    with mutate() as s:
        if update_id not in s["processed_ids"]:
            s["processed_ids"].append(update_id)


# ─── main agent session — §4.5 ───────────────────────────────────────────────

def get_session() -> dict | None:
    return read().get("session")


def start_session(window_size: int) -> dict:
    session = {
        "id": str(uuid.uuid4()),
        "started_at": time.time(),
        "window_size": window_size,
        "tokens": 0,
        "turns": 0,
    }
    with mutate() as s:
        s["session"] = session
    return session


def record_turn_usage(tokens: int) -> dict | None:
    """Store the true running context size, taken from `claude -p`'s result
    message — not an estimate from characters (§4.5)."""
    with mutate() as s:
        if not s.get("session"):
            return None
        s["session"]["tokens"] = tokens
        s["session"]["turns"] = s["session"].get("turns", 0) + 1
        return dict(s["session"])


def clear_session() -> dict | None:
    with mutate() as s:
        old = s.get("session")
        s["session"] = None
        return old


# ─── retry queue — visible, never a silent dead-letter (§4.2) ────────────────

def queue_retry(entry: dict) -> None:
    with mutate() as s:
        s["retry"].append({**entry, "at": time.time()})


def retry_count() -> int:
    return len(read().get("retry") or [])


def take_retries() -> list[dict]:
    with mutate() as s:
        items = list(s.get("retry") or [])
        s["retry"] = []
        return items
