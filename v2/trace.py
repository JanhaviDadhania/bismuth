"""The trace — §5. Append-only JSONL, never rotated, `seq`-ordered.

The trace is the single source of truth. The board and the task list are
projections of it, never separate files that can drift.

Three fields on every event:
  ts        ISO 8601 local time with offset — human-readable
  seq       global, gapless, monotonic integer — THE authoritative sort key
  trace_id  Telegram's update_id — joins every event for one note

`seq` exists because `ts` is not a safe sort key: one turn can spawn four
sub-agents inside a millisecond, and timestamps with different UTC offsets
(travel, DST) do not sort lexicographically. It is assigned under the same
lock that appends the line, so it is gapless — and a gap therefore means an
event was lost, which makes trace completeness checkable rather than assumed.
"""

from __future__ import annotations

import fcntl
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from . import config as cfg


def now_iso() -> str:
    """Local time with offset, e.g. 2026-08-31T14:30:41+05:30."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def month_file(when: datetime | None = None) -> Path:
    when = when or datetime.now().astimezone()
    return cfg.TRACE_DIR / f"log-{when:%Y-%m}.jsonl"


def _cap(value: Any, limit: int) -> Any:
    """Per-event size cap (§5). With no rotation, this is the only thing
    bounding trace growth, and one sub-agent tool result can be an entire
    file read. Truncation is marked, never silent."""
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"…[truncated {len(value) - limit} chars]"
    if isinstance(value, dict):
        return {k: _cap(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_cap(v, limit) for v in value]
    return value


class Trace:
    """Appends events under a file lock, assigning seq in the same critical
    section. Safe across threads and across processes."""

    def __init__(self, event_cap: int | None = None):
        cfg.ensure_dirs()
        self.event_cap = cfg.TRACE_EVENT_CAP if event_cap is None else event_cap
        cfg.TRACE_LOCK.parent.mkdir(parents=True, exist_ok=True)

    # ─── writing ────────────────────────────────────────────────────────────

    def append(self, event_type: str, trace_id: str | None = None, **fields: Any) -> dict:
        event = {"ts": now_iso(), "seq": None, "type": event_type,
                 "trace_id": trace_id}
        event.update({k: _cap(v, self.event_cap) for k, v in fields.items()})

        with open(cfg.TRACE_LOCK, "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                event["seq"] = self._next_seq_locked()
                path = month_file()
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
                    f.flush()
                    import os
                    os.fsync(f.fileno())
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
        return event

    def _next_seq_locked(self) -> int:
        """Caller holds the lock. The counter file is a cache; if it is missing
        or behind the trace (hand-edit, restore from backup) it is rebuilt from
        the trace itself, so seq can never go backwards and collide."""
        cached = 0
        if cfg.TRACE_SEQ_FILE.exists():
            try:
                cached = int(cfg.TRACE_SEQ_FILE.read_text().strip() or 0)
            except ValueError:
                cached = 0
        if cached == 0:
            cached = self.max_seq_on_disk()
        nxt = cached + 1
        cfg.TRACE_SEQ_FILE.write_text(str(nxt))
        return nxt

    def max_seq_on_disk(self) -> int:
        highest = 0
        for event in self.iter_events():
            seq = event.get("seq")
            if isinstance(seq, int) and seq > highest:
                highest = seq
        return highest

    # ─── reading ────────────────────────────────────────────────────────────

    @staticmethod
    def files() -> list[Path]:
        if not cfg.TRACE_DIR.exists():
            return []
        return sorted(cfg.TRACE_DIR.glob("log-*.jsonl"))

    @classmethod
    def iter_events(cls, types: set[str] | None = None) -> Iterator[dict]:
        """Every event, in file order (which is seq order per file, and the
        files are month-partitioned, so overall seq order)."""
        for path in cls.files():
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line.startswith("{"):
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if types is None or event.get("type") in types:
                        yield event

    @classmethod
    def seq_gaps(cls) -> list[tuple[int, int]]:
        """Ranges missing from the trace. A non-empty result means events were
        lost — the property that makes completeness checkable (§5)."""
        seqs = sorted(e["seq"] for e in cls.iter_events()
                      if isinstance(e.get("seq"), int))
        gaps: list[tuple[int, int]] = []
        for prev, nxt in zip(seqs, seqs[1:]):
            if nxt > prev + 1:
                gaps.append((prev + 1, nxt - 1))
        return gaps


_default: Trace | None = None


def trace() -> Trace:
    """Process-wide Trace. Cheap to call; the lock is per-append."""
    global _default
    if _default is None:
        _default = Trace()
    return _default
