"""
Bismuth v2 harness — always-on message router and agent orchestrator.

Owns:
  - Telegram long-polling
  - Agent invocation (assistant ↔ coffeechat)
  - Executor lifecycle (spawn, monitor, reap)
  - Exit-token parsing
  - State persistence (memory/.harness/state.json)
  - Calendar polling stub (1-hour timer; calendar tool TBD)

Design doc: docs/v1/HARNESS_DESIGN.md
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import BASE_DIR, MEMORY_DIR, load_config


# ─── Paths ───────────────────────────────────────────────────────────────────

HARNESS_DIR = MEMORY_DIR / ".harness"
STATE_FILE = HARNESS_DIR / "state.json"
STATE_BACKUP = HARNESS_DIR / ".state.json.bak"
STATE_TMP = HARNESS_DIR / ".state.json.tmp"
LOG_FILE = HARNESS_DIR / "log.jsonl"
PENDING_TASKS_DIR = HARNESS_DIR / "pending_tasks"
INBOX_DIR = HARNESS_DIR / "inbox"
INBOX_PRUNE_AGE_DAYS = 7

SYNTHETIC_INBOX = HARNESS_DIR / "synthetic_inbox"
WATCHER_STATE_DIR = HARNESS_DIR / "watcher_state"
WATCHERS_DIR = BASE_DIR / "tools" / "watchers"


# ─── Tunables ────────────────────────────────────────────────────────────────

EXECUTOR_CAP = 3
LONG_POLL_TIMEOUT = 50      # seconds — Telegram thread holds the connection this long
MAIN_TICK = 1.0             # seconds — main loop max idle wait between mailbox/buffer checks
AGENT_TIMEOUT = 600
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

# Synthetic inbox guards
MAX_SYNTHETIC_MESSAGE = 10_000      # chars; longer messages get truncated
MAX_FILES_PER_TICK = 20             # cap drain to prevent prompt-bomb on crash-loop

# Watcher supervisor
WATCHER_SWEEP_INTERVAL = 60               # seconds between supervisor sweeps
WATCHER_BACKOFF_BASE = 30                 # seconds; doubled per consecutive crash
WATCHER_BACKOFF_MAX = 1800                # cap at 30 min between restart attempts
WATCHER_HEALTHY_UPTIME = 300              # seconds — uptime needed to reset crash count
WATCHER_FAILURE_NOTIFY_THRESHOLD = 3      # consecutive crashes before notifying agent


# ─── Environment ─────────────────────────────────────────────────────────────

def _load_env():
    env = load_config().get("env", {})
    for key, value in env.items():
        if value:
            os.environ.setdefault(key, str(value))


def _tg_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise EnvironmentError("TELEGRAM_BOT_TOKEN not set")
    return token


def _tg_chat_id() -> str:
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise EnvironmentError("TELEGRAM_CHAT_ID not set")
    return chat_id


# ─── State ───────────────────────────────────────────────────────────────────

def default_state() -> dict:
    return {
        "active_agent": "assistant",
        "telegram_offset": 0,
        "executors": {},
        "pending_buffer": [],
        "sessions": {},
        "watchers": {},
    }


# ─── Sessions ────────────────────────────────────────────────────────────────

def get_or_create_session(agent_name: str, state: dict) -> tuple[str, bool]:
    """Return (session_uuid, is_new). Lazily creates and stores UUID."""
    sessions = state.setdefault("sessions", {})
    existing = sessions.get(agent_name)
    if existing:
        return existing, False
    new_id = str(uuid.uuid4())
    sessions[agent_name] = new_id
    return new_id, True


def reset_session(agent_name: str, state: dict):
    """Drop the session UUID for an agent. Next turn will start a fresh session."""
    sessions = state.setdefault("sessions", {})
    old = sessions.pop(agent_name, None)
    if old:
        log_event("session_reset", agent=agent_name, old_session=old)


SESSION_START_ASSISTANT = (
    "[session start — read mood.md and second_order_thoughts.md once for context; "
    "you won't re-read them during this session]"
)

SESSION_START_COFFEECHAT = (
    "[session start — read projects/{project}/vision.md, projects/{project}/nexttodo.md, "
    "projects/{project}/reference/register.md (if it exists), projects/{project}/coffeechat/ "
    "(if it exists), last few entries of mood.md, and second_order_thoughts.md once for "
    "context; you won't re-read them during this session]"
)


def session_start_marker(agent_name: str) -> str:
    if agent_name == "assistant":
        return SESSION_START_ASSISTANT
    if agent_name.startswith("coffeechat:"):
        project = agent_name.split(":", 1)[1]
        return SESSION_START_COFFEECHAT.format(project=project)
    return "[session start]"


SYNTHETIC_INBOX_README = """\
This directory is the **synthetic inbox** — any process can drop text files
here and the harness will treat them as synthetic messages to the active
agent on its next tick (≤ 1 second).

## Atomic-write contract

Writers MUST:
1. Write to `<name>.txt.tmp` first.
2. `os.rename` (or shell `mv`) to `<name>.txt`.

The harness only reads files ending in `.txt`. Partial `.tmp` files are
ignored, so a half-written file can never be picked up.

## What happens to files

Each `.txt` file is read once, its contents become one synthetic message,
and the file is deleted. The harness sorts by mtime (chronological), caps
at 20 files per tick, and truncates messages longer than 10 KB.

## One-way contract

Writers only WRITE here. Never read or unlink — that's the harness's job.
"""

WATCHERS_README = """\
This directory holds **watcher scripts** — long-running processes that
sense the outside world (filesystem, camera, calendar, webhooks, …) and
poke the assistant by dropping synthetic messages into `SYNTHETIC_INBOX`.

The harness's watcher supervisor starts each `*.py` file here as a child
process, restarts crashed ones with exponential backoff, and notifies the
agent after 3 consecutive crashes.

## File naming

- `<name>.py` — picked up and auto-spawned.
- `_<name>.py` — underscore prefix = ignored (templates, disabled).

## Watcher contract

Every watcher MUST:

1. Run an indefinite loop (or block on its event source).
2. Drop messages into `os.environ["SYNTHETIC_INBOX"]` using atomic writes:
   write to `<name>.txt.tmp`, then `os.rename` to `<name>.txt`.
3. Persist any state to `os.environ["WATCHER_STATE_DIR"]` (a per-watcher
   directory the harness creates).
4. Log to stderr — captured to `{HARNESS_DIR}/watcher_<stem>.log`.
   Don't use stdout for coordination; use the inbox.
5. NEVER read from `SYNTHETIC_INBOX`. The harness owns the drain side.
6. Exit non-zero only on genuine failure. The supervisor backs off
   exponentially (30s base, doubling, capped at 30 min) and after 3
   consecutive crashes drops a `[watcher: <name> is failing …]` synthetic
   message so the agent learns about it.

## Environment variables (set by the supervisor)

| Var                  | Meaning                                                |
|----------------------|--------------------------------------------------------|
| `SYNTHETIC_INBOX`    | Absolute path; where to drop messages.                 |
| `WATCHER_STATE_DIR`  | Absolute path; per-watcher persistent state directory. |
| `BISMUTH_BASE`       | Absolute path; repo root.                              |
| `BISMUTH_MEMORY`     | Absolute path; memory root.                            |

## Message format

Convention: prefix each message with `[source: …]` so skill files can
teach the agent how to react. Examples:

- `[fs-dropbox: paper.pdf saved at /…/paper.pdf]`
- `[daily reminders] …`
- `[camera: motion detected at 14:02; snapshot at /tmp/cam_x.jpg]`

Not enforced by the harness — just a convention.

## Start with `_template.py`

Copy `_template.py` (the underscore prefix makes it inert) to `<name>.py`
when you're ready to enable a new watcher. The supervisor picks it up on
its next sweep (within 60 seconds).
"""


def _write_if_missing(path: Path, content: str):
    if not path.exists():
        path.write_text(content)


def init_dirs():
    HARNESS_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_TASKS_DIR.mkdir(parents=True, exist_ok=True)
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    SYNTHETIC_INBOX.mkdir(parents=True, exist_ok=True)
    WATCHER_STATE_DIR.mkdir(parents=True, exist_ok=True)
    WATCHERS_DIR.mkdir(parents=True, exist_ok=True)
    _write_if_missing(SYNTHETIC_INBOX / "README.md", SYNTHETIC_INBOX_README)
    _write_if_missing(WATCHERS_DIR / "README.md", WATCHERS_README)


def prune_inbox():
    """Delete inbox files older than INBOX_PRUNE_AGE_DAYS."""
    cutoff = time.time() - (INBOX_PRUNE_AGE_DAYS * 86400)
    for f in INBOX_DIR.iterdir():
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                log_event("inbox_pruned", file=f.name)
        except Exception:
            pass


def read_state() -> dict:
    for path in (STATE_FILE, STATE_BACKUP):
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            log_event("state_corrupt", path=str(path))
    return default_state()


def write_state(state: dict):
    STATE_TMP.write_text(json.dumps(state, indent=2, sort_keys=True))
    with open(STATE_TMP, "rb+") as f:
        os.fsync(f.fileno())
    if STATE_FILE.exists():
        os.replace(STATE_FILE, STATE_BACKUP)
    os.replace(STATE_TMP, STATE_FILE)


# ─── Logging ─────────────────────────────────────────────────────────────────

def log_event(event_type: str, **kwargs):
    entry = {"ts": datetime.now().isoformat(), "type": event_type, **kwargs}
    try:
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
    print(f"[harness] {event_type} {kwargs}", flush=True)


# ─── Telegram ────────────────────────────────────────────────────────────────

def _telegram_get_file_url(file_id: str) -> str | None:
    """Resolve file_id to a downloadable URL."""
    url = TELEGRAM_API.format(token=_tg_token(), method="getFile")
    try:
        resp = requests.get(url, params={"file_id": file_id}, timeout=15)
        data = resp.json()
        if not data.get("ok"):
            return None
        file_path = data["result"]["file_path"]
        return f"https://api.telegram.org/file/bot{_tg_token()}/{file_path}"
    except Exception as e:
        log_event("telegram_getfile_error", error=str(e), file_id=file_id)
        return None


def _download_telegram_file(file_id: str, dest: Path) -> bool:
    file_url = _telegram_get_file_url(file_id)
    if not file_url:
        return False
    try:
        resp = requests.get(file_url, timeout=60)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return True
    except Exception as e:
        log_event("telegram_download_error", error=str(e), file_id=file_id)
        return False


def _transcribe_audio(path: Path) -> str | None:
    """Voice/audio → text via tools/transcribe.py. Returns None on failure."""
    try:
        from tools.transcribe import transcribe
        result = transcribe(str(path))
        if result.get("success"):
            return result.get("transcript", "").strip()
        log_event("transcribe_failed", error=result.get("error"), path=str(path))
        return None
    except Exception as e:
        log_event("transcribe_exception", error=str(e), path=str(path))
        return None


def _render_message(msg: dict, is_edited: bool = False) -> str | None:
    """
    Convert one Telegram message into a single synthetic string for the agent.
    Downloads media to INBOX_DIR. Transcribes voice/audio. Returns None for
    fully unsupported types.
    """
    msg_id = msg.get("message_id", "x")
    caption = msg.get("caption", "").strip()
    edit_prefix = "[edited] " if is_edited else ""

    if "text" in msg:
        return edit_prefix + msg["text"]

    if "voice" in msg:
        file_id = msg["voice"]["file_id"]
        dest = INBOX_DIR / f"voice_{msg_id}.ogg"
        if _download_telegram_file(file_id, dest):
            transcript = _transcribe_audio(dest)
            if transcript:
                return f"{edit_prefix}[telegram voice — saved at {dest}]: {transcript}"
            return f"{edit_prefix}[telegram voice — saved at {dest}, transcription failed]"
        return f"{edit_prefix}[telegram voice — download failed]"

    if "audio" in msg:
        file_id = msg["audio"]["file_id"]
        ext = (msg["audio"].get("mime_type", "audio/mp3").split("/")[-1] or "mp3")
        dest = INBOX_DIR / f"audio_{msg_id}.{ext}"
        if _download_telegram_file(file_id, dest):
            transcript = _transcribe_audio(dest)
            if transcript:
                base = f"{edit_prefix}[telegram audio — saved at {dest}]: {transcript}"
                return base + (f" | caption: {caption}" if caption else "")
            return f"{edit_prefix}[telegram audio — saved at {dest}, transcription failed]" + (
                f" | caption: {caption}" if caption else "")
        return f"{edit_prefix}[telegram audio — download failed]"

    if "photo" in msg:
        # photo is an array of sizes; take the largest (last)
        photo = msg["photo"][-1]
        file_id = photo["file_id"]
        dest = INBOX_DIR / f"photo_{msg_id}.jpg"
        if _download_telegram_file(file_id, dest):
            base = f"{edit_prefix}[telegram photo — saved at {dest}]"
            return base + (f" caption: {caption}" if caption else "")
        return f"{edit_prefix}[telegram photo — download failed]"

    if "video" in msg:
        file_id = msg["video"]["file_id"]
        dest = INBOX_DIR / f"video_{msg_id}.mp4"
        if _download_telegram_file(file_id, dest):
            base = f"{edit_prefix}[telegram video — saved at {dest}]"
            return base + (f" caption: {caption}" if caption else "")
        return f"{edit_prefix}[telegram video — download failed]"

    if "document" in msg:
        doc = msg["document"]
        file_id = doc["file_id"]
        filename = doc.get("file_name", f"doc_{msg_id}")
        # sanitize
        safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in filename)
        dest = INBOX_DIR / f"doc_{msg_id}_{safe_name}"
        if _download_telegram_file(file_id, dest):
            base = f"{edit_prefix}[telegram document {filename} — saved at {dest}]"
            return base + (f" caption: {caption}" if caption else "")
        return f"{edit_prefix}[telegram document {filename} — download failed]"

    # Unsupported types: sticker, location, contact, poll, etc.
    for unsupported in ("sticker", "location", "contact", "poll", "venue", "animation"):
        if unsupported in msg:
            log_event("unsupported_telegram_type", type=unsupported, msg_id=msg_id)
            return f"{edit_prefix}[telegram {unsupported} — cannot process; tell janhavi you can't handle this type]"

    log_event("unknown_telegram_message", msg_id=msg_id, keys=list(msg.keys()))
    return None


def _fetch_telegram(offset: int, timeout: int) -> tuple[list[str], int]:
    """One getUpdates call. Returns (rendered messages, new offset)."""
    url = TELEGRAM_API.format(token=_tg_token(), method="getUpdates")
    try:
        resp = requests.get(
            url,
            params={"offset": offset, "timeout": timeout},
            timeout=timeout + 10,
        )
        data = resp.json()
        if not data.get("ok"):
            return [], offset
        updates = data.get("result", [])
        if not updates:
            return [], offset
        new_offset = updates[-1]["update_id"] + 1
        rendered = []
        for u in updates:
            msg = u.get("message")
            edited = u.get("edited_message")
            if msg:
                line = _render_message(msg, is_edited=False)
            elif edited:
                line = _render_message(edited, is_edited=True)
            else:
                continue
            if line:
                rendered.append(line)
        return rendered, new_offset
    except Exception as e:
        log_event("telegram_error", error=str(e))
        return [], offset


def telegram_send(text: str):
    url = TELEGRAM_API.format(token=_tg_token(), method="sendMessage")
    try:
        requests.post(url, data={"chat_id": _tg_chat_id(), "text": text}, timeout=15)
    except Exception as e:
        log_event("telegram_send_error", error=str(e))


# ─── Telegram background thread ──────────────────────────────────────────────

class TelegramPoller(threading.Thread):
    """
    Background thread that long-polls Telegram and deposits messages into a
    shared inbox. Wakes the main loop via tg_event so the new agent runs
    immediately instead of waiting for the next long-poll cycle to expire.
    """

    def __init__(self, initial_offset: int):
        super().__init__(daemon=True, name="telegram-poller")
        self.offset = initial_offset
        self.inbox: list[str] = []
        self.lock = threading.Lock()
        self.event = threading.Event()
        self.shutdown = threading.Event()

    def run(self):
        while not self.shutdown.is_set():
            with self.lock:
                offset = self.offset
            messages, new_offset = _fetch_telegram(offset, LONG_POLL_TIMEOUT)
            with self.lock:
                self.offset = new_offset
                if messages:
                    self.inbox.extend(messages)
            if messages:
                self.event.set()

    def drain(self) -> tuple[list[str], int]:
        """Atomically take all queued messages + current offset."""
        with self.lock:
            messages = self.inbox[:]
            self.inbox.clear()
            return messages, self.offset

    def stop(self):
        self.shutdown.set()


# ─── Synthetic inbox ─────────────────────────────────────────────────────────

def read_synthetic_inbox() -> list[str]:
    """Drain text files from SYNTHETIC_INBOX. Caps file count + message size.
    Files are consumed (deleted) after read. Sorted by mtime (chronological)."""
    out: list[str] = []
    try:
        files = [f for f in SYNTHETIC_INBOX.iterdir()
                 if f.is_file() and f.name.endswith(".txt")]
    except FileNotFoundError:
        return []
    files.sort(key=lambda f: f.stat().st_mtime)

    for f in files[:MAX_FILES_PER_TICK]:
        try:
            text = f.read_text()
            original_len = len(text)
            if original_len > MAX_SYNTHETIC_MESSAGE:
                text = (text[:MAX_SYNTHETIC_MESSAGE]
                        + f"\n...[truncated; original {original_len} chars]")
                log_event("synthetic_msg_truncated", file=f.name, length=original_len)
            out.append(text.strip())
            f.unlink()
        except Exception as e:
            log_event("synthetic_inbox_read_error", file=f.name, error=str(e))

    if len(files) > MAX_FILES_PER_TICK:
        log_event("synthetic_inbox_throttled",
                  drained=MAX_FILES_PER_TICK,
                  remaining=len(files) - MAX_FILES_PER_TICK)
    return out


# ─── Watcher supervisor ──────────────────────────────────────────────────────

def kill_orphan_watchers():
    """On boot: kill any leftover watcher processes from a previous harness.
    Watchers are stateless across boots; the supervisor's first sweep spawns
    fresh ones."""
    try:
        r = subprocess.run(
            ["pgrep", "-f", r"tools/watchers/.*\.py"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception as e:
        log_event("pgrep_failed", error=str(e))
        return
    for pid_str in r.stdout.split():
        try:
            pid = int(pid_str)
            os.kill(pid, 9)
            log_event("orphan_watcher_killed", pid=pid)
        except (ProcessLookupError, PermissionError, ValueError):
            pass


def _pid_is_our_watcher(pid: int, script_name: str) -> bool:
    """Verify pid is alive AND its cmdline references our watcher script.
    Defends against PID reuse by unrelated processes."""
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    try:
        r = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=2,
        )
        return script_name in r.stdout
    except Exception:
        # If ps fails, fall back to trusting the PID-alive check
        return True


def _spawn_watcher(script: Path) -> subprocess.Popen:
    log_path = HARNESS_DIR / f"watcher_{script.stem}.log"
    state_dir = WATCHER_STATE_DIR / script.stem
    state_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["SYNTHETIC_INBOX"] = str(SYNTHETIC_INBOX)
    env["BISMUTH_BASE"] = str(BASE_DIR)
    env["BISMUTH_MEMORY"] = str(MEMORY_DIR)
    env["WATCHER_STATE_DIR"] = str(state_dir)

    with open(log_path, "a") as logf:
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            cwd=str(BASE_DIR),
            stdout=logf, stderr=subprocess.STDOUT,
            env=env,
        )
    return proc


def _notify_watcher_failure(name: str):
    """Drop a synthetic message into the inbox so the agent learns about a
    persistently failing watcher."""
    log_path = HARNESS_DIR / f"watcher_{Path(name).stem}.log"
    msg = (f"[watcher: {name} is failing repeatedly — "
           f"last {WATCHER_FAILURE_NOTIFY_THRESHOLD} restarts crashed. "
           f"Check {log_path} for the error.]")
    fname = f"watcher_failure_{Path(name).stem}_{int(time.time())}.txt"
    tmp = SYNTHETIC_INBOX / (fname + ".tmp")
    tmp.write_text(msg)
    tmp.rename(SYNTHETIC_INBOX / fname)
    log_event("watcher_failure_notified", name=name)


def supervise_watchers(state: dict):
    """Ensure every tools/watchers/<name>.py has a live child.
    Backs off exponentially on consecutive crashes; notifies the agent after
    WATCHER_FAILURE_NOTIFY_THRESHOLD crashes."""
    tracked = state.setdefault("watchers", {})
    now = time.time()

    # 1. Drop watchers whose script file no longer exists
    for name in list(tracked.keys()):
        if not (WATCHERS_DIR / name).exists():
            try:
                os.kill(tracked[name]["pid"], 9)
            except (ProcessLookupError, PermissionError):
                pass
            del tracked[name]
            log_event("watcher_removed", name=name)

    # 2. For each script present, ensure a process is live
    for script in sorted(WATCHERS_DIR.glob("*.py")):
        if script.name.startswith("_"):
            continue  # template / disabled

        name = script.name
        info = tracked.get(name)

        if info and _pid_is_our_watcher(info["pid"], name):
            continue  # healthy

        # Determine consecutive crash count
        if info:
            uptime = now - info.get("last_spawn_ts", now)
            if uptime >= WATCHER_HEALTHY_UPTIME:
                crash_count = 1
            else:
                crash_count = info.get("crash_count", 0) + 1
        else:
            crash_count = 0  # first ever spawn — no backoff

        # Backoff window check
        if info and crash_count > 0:
            backoff = min(
                WATCHER_BACKOFF_BASE * (2 ** max(crash_count - 1, 0)),
                WATCHER_BACKOFF_MAX,
            )
            if now - info.get("last_spawn_ts", 0) < backoff:
                continue

        # Spawn (or respawn)
        try:
            proc = _spawn_watcher(script)
        except Exception as e:
            log_event("watcher_spawn_error", name=name, error=str(e))
            continue

        prev_notified = info.get("notified", False) if info else False
        tracked[name] = {
            "pid": proc.pid,
            "last_spawn_ts": now,
            "crash_count": crash_count,
            "notified": False if crash_count == 0 else prev_notified,
        }
        log_event("watcher_spawned", name=name, pid=proc.pid,
                  crash_count=crash_count)

        # Surface persistent failures back to the agent — once per failure run
        if (crash_count >= WATCHER_FAILURE_NOTIFY_THRESHOLD
                and not tracked[name]["notified"]):
            _notify_watcher_failure(name)
            tracked[name]["notified"] = True


# ─── Mailbox ─────────────────────────────────────────────────────────────────

def read_mailbox(state: dict) -> list[str]:
    """Collect synthetic messages from executor scratch dirs."""
    synthetic = []
    for uid, info in list(state.get("executors", {}).items()):
        exec_dir = HARNESS_DIR / f"executor_{uid}"
        status_file = exec_dir / "status"
        if not status_file.exists():
            continue
        status = status_file.read_text().strip()
        short = uid[:8]
        project = info.get("project", "general")

        if status == "asking":
            q = exec_dir / "question.txt"
            ans = exec_dir / "answer.txt"
            if q.exists() and not ans.exists() and not info.get("question_relayed"):
                question = q.read_text().strip()
                synthetic.append(
                    f"[executor #{short} for {project}]: {question}\n"
                    f"To answer, write your reply to: {ans}"
                )
                info["question_relayed"] = True

        elif status == "done" and not info.get("result_relayed"):
            summary_file = exec_dir / "result_summary.txt"
            summary = summary_file.read_text().strip() if summary_file.exists() else "(no summary)"
            synthetic.append(f"[executor #{short} for {project}]: DONE — {summary}")
            info["result_relayed"] = True
            info["status"] = "done"

        elif status == "failed" and not info.get("result_relayed"):
            synthetic.append(f"[executor #{short} for {project}]: FAILED — check {exec_dir}/stderr.log")
            info["result_relayed"] = True
            info["status"] = "failed"

    return synthetic


# ─── Agent invocation ────────────────────────────────────────────────────────

def _substitute(text: str, project: str = "general") -> str:
    return (text
            .replace("{MEMORY_DIR}", str(MEMORY_DIR))
            .replace("{HARNESS_DIR}", str(HARNESS_DIR))
            .replace("{PENDING_TASKS_DIR}", str(PENDING_TASKS_DIR))
            .replace("{SYNTHETIC_INBOX}", str(SYNTHETIC_INBOX))
            .replace("{WATCHERS_DIR}", str(WATCHERS_DIR))
            .replace("{TELEGRAM_CLI}", str(BASE_DIR / "tools" / "telegram_cli.py"))
            .replace("{project_name}", project)
            .replace("{PROJECT}", project))


SKILL_SEPARATOR = "\n\n---\n\n"


def _load_skills(skills_dir: Path) -> str:
    """Concatenate sorted *.md files under skills_dir. Returns '' if dir missing or empty."""
    if not skills_dir.is_dir():
        return ""
    parts = []
    for f in sorted(skills_dir.glob("*.md")):
        try:
            parts.append(f.read_text())
        except Exception as e:
            log_event("skill_load_error", file=str(f), error=str(e))
    return SKILL_SEPARATOR.join(parts)


def build_prompt(agent_name: str) -> str:
    prompts_dir = BASE_DIR / "prompts"
    if agent_name == "assistant":
        base = (prompts_dir / "assistant.md").read_text()
        skills = _load_skills(prompts_dir / "skills" / "assistant")
        full = base + (SKILL_SEPARATOR + skills if skills else "")
        return _substitute(full)
    if agent_name.startswith("coffeechat:"):
        project = agent_name.split(":", 1)[1]
        base = (prompts_dir / "coffeechat.md").read_text()
        global_skills = _load_skills(prompts_dir / "skills" / "coffeechat")
        project_skills = _load_skills(MEMORY_DIR / "projects" / project / "skills")
        extras = SKILL_SEPARATOR.join(s for s in (global_skills, project_skills) if s)
        full = base + (SKILL_SEPARATOR + extras if extras else "")
        return _substitute(full, project=project)
    raise ValueError(f"unknown agent: {agent_name}")


def _session_not_found(stderr: str, session_id: str) -> bool:
    lower = stderr.lower()
    return session_id in stderr and "no" in lower and "found" in lower


def _invoke_claude(user_msg: str, system: str, session_id: str, is_new: bool):
    """One claude subprocess call. New sessions create with --session-id and
    receive the system prompt; resumed sessions use --resume and inherit the
    prompt baked in at creation time."""
    if is_new:
        cmd = ["claude", "-p", user_msg,
               "--session-id", session_id,
               "--system-prompt", system,
               "--dangerously-skip-permissions"]
    else:
        cmd = ["claude", "-p", user_msg,
               "--resume", session_id,
               "--dangerously-skip-permissions"]
    return subprocess.run(
        cmd,
        cwd=str(BASE_DIR),
        capture_output=True, text=True,
        timeout=AGENT_TIMEOUT,
    )


def run_agent(agent_name: str, batch: list[str], state: dict) -> tuple[str, int]:
    system = build_prompt(agent_name)
    session_id, is_new = get_or_create_session(agent_name, state)
    if is_new:
        batch = [session_start_marker(agent_name)] + batch
    user_msg = "Incoming batch (in order received):\n" + "\n".join(
        f"{i+1}. {m}" for i, m in enumerate(batch)
    )
    log_event("agent_start", agent=agent_name, batch_size=len(batch),
              session=session_id, new_session=is_new)
    try:
        result = _invoke_claude(user_msg, system, session_id, is_new)
        # Resumed session might be gone from claude's store (transcript pruned,
        # disk wipe, etc.). Detect, regenerate, and re-run as a fresh session.
        if (not is_new
                and result.returncode != 0
                and _session_not_found(result.stderr or "", session_id)):
            log_event("session_lost", agent=agent_name, session=session_id)
            reset_session(agent_name, state)
            new_id, _ = get_or_create_session(agent_name, state)
            batch = [session_start_marker(agent_name)] + batch
            user_msg = "Incoming batch (in order received):\n" + "\n".join(
                f"{i+1}. {m}" for i, m in enumerate(batch)
            )
            log_event("agent_retry_fresh", agent=agent_name, session=new_id)
            result = _invoke_claude(user_msg, system, new_id, True)
        log_event("agent_done", agent=agent_name, exit_code=result.returncode)
        return result.stdout, result.returncode
    except subprocess.TimeoutExpired:
        log_event("agent_timeout", agent=agent_name)
        return "", -1


# ─── Exit token parsing ──────────────────────────────────────────────────────

TOKEN_PATTERNS = {
    "SWITCH":          re.compile(r"^SWITCH:(.+)$", re.MULTILINE),
    "SPAWN_EXECUTOR":  re.compile(r"^SPAWN_EXECUTOR:(.+)$", re.MULTILINE),
    "PENDING":         re.compile(r"^PENDING:(.+)$", re.MULTILINE),
    "RESET_SESSION":   re.compile(r"^RESET_SESSION\s*$", re.MULTILINE),
    "HALT":            re.compile(r"^HALT\s*$", re.MULTILINE),
}


def parse_tokens(stdout: str) -> dict:
    tokens = {}
    for name, pattern in TOKEN_PATTERNS.items():
        m = pattern.search(stdout)
        if m:
            tokens[name] = m.group(1).strip() if m.groups() else True
    return tokens


# ─── Executors ───────────────────────────────────────────────────────────────

def running_count(state: dict) -> int:
    return sum(1 for e in state["executors"].values() if e.get("status") == "running")


def spawn_executor(task_id: str, project: str, state: dict) -> bool:
    pending = PENDING_TASKS_DIR / f"{task_id}.md"
    if not pending.exists():
        log_event("spawn_failed_no_task", task_id=task_id)
        return False

    if running_count(state) >= EXECUTOR_CAP:
        log_event("executor_at_cap", task_id=task_id)
        telegram_send(f"executor cap ({EXECUTOR_CAP}) reached; task {task_id} queued — re-spawn later")
        return False

    uid = uuid.uuid4().hex
    exec_dir = HARNESS_DIR / f"executor_{uid}"
    exec_dir.mkdir(parents=True, exist_ok=True)
    (exec_dir / "task.md").write_text(pending.read_text())
    (exec_dir / "status").write_text("running")
    pending.unlink()

    template = (BASE_DIR / "prompts" / "executor.md").read_text()
    system = (template
              .replace("{MEMORY_DIR}", str(MEMORY_DIR))
              .replace("{EXEC_DIR}", str(exec_dir))
              .replace("{PROJECT}", project))

    user_msg = f"Your task is in {exec_dir / 'task.md'}. Read it and begin."

    stdout_log = open(exec_dir / "stdout.log", "w")
    stderr_log = open(exec_dir / "stderr.log", "w")
    proc = subprocess.Popen(
        ["claude", "-p", user_msg,
         "--system-prompt", system,
         "--dangerously-skip-permissions"],
        cwd=str(BASE_DIR),
        stdout=stdout_log,
        stderr=stderr_log,
    )
    state["executors"][uid] = {
        "pid": proc.pid,
        "project": project,
        "task_id": task_id,
        "started_at": datetime.now().isoformat(),
        "status": "running",
    }
    log_event("executor_spawned", uuid=uid, pid=proc.pid, project=project, task_id=task_id)
    return True


def reap_executors(state: dict):
    """Reconcile on-disk status with process state."""
    for uid, info in list(state["executors"].items()):
        exec_dir = HARNESS_DIR / f"executor_{uid}"
        status_file = exec_dir / "status"
        on_disk = status_file.read_text().strip() if status_file.exists() else None

        # Promote disk status to state
        if on_disk in ("done", "failed", "asking"):
            info["status"] = on_disk
            continue

        # If process is gone but disk still says running → mark failed
        try:
            os.kill(info["pid"], 0)
        except (ProcessLookupError, PermissionError):
            if info["status"] == "running":
                info["status"] = "failed"
                if status_file.exists():
                    status_file.write_text("failed")
                log_event("executor_died", uuid=uid)


def halt_all(state: dict):
    for uid, info in state["executors"].items():
        if info.get("status") == "running":
            try:
                os.kill(info["pid"], 9)
            except ProcessLookupError:
                pass
            info["status"] = "failed"
            log_event("executor_killed", uuid=uid, reason="HALT")


# ─── Token handling ──────────────────────────────────────────────────────────

def handle_tokens(tokens: dict, state: dict):
    if "HALT" in tokens:
        halt_all(state)
        state["pending_buffer"] = []
        state["active_agent"] = "assistant"
        telegram_send("HALT — all executors stopped, back to assistant.")
        log_event("halt")

    if "PENDING" in tokens:
        try:
            buf = json.loads(tokens["PENDING"])
            if isinstance(buf, list):
                state["pending_buffer"] = buf
        except json.JSONDecodeError:
            log_event("pending_parse_error", raw=tokens["PENDING"])

    if "SPAWN_EXECUTOR" in tokens:
        payload = tokens["SPAWN_EXECUTOR"]
        if ":" in payload:
            task_id, project = payload.split(":", 1)
        else:
            task_id, project = payload, "general"
        spawn_executor(task_id.strip(), project.strip(), state)

    if "RESET_SESSION" in tokens:
        reset_session(state["active_agent"], state)

    if "SWITCH" in tokens:
        spec = tokens["SWITCH"]
        if spec == "assistant" or spec.startswith("coffeechat:"):
            state["active_agent"] = spec
            # Cold switch: nothing for the new agent to chew on. Inject a small
            # synthetic so it runs once and greets janhavi.
            if not state.get("pending_buffer"):
                state["pending_buffer"] = ["[fresh switch — greet janhavi briefly and warmly]"]
            log_event("switch", to=spec)
        else:
            log_event("unknown_switch", spec=spec)


# ─── Main loop ───────────────────────────────────────────────────────────────

def main():
    _load_env()
    init_dirs()
    prune_inbox()
    kill_orphan_watchers()
    state = read_state()
    log_event("harness_start", active_agent=state["active_agent"])

    poller = TelegramPoller(initial_offset=state["telegram_offset"])
    poller.start()

    last_watcher_sweep = 0.0

    try:
        while True:
            try:
                # Wait for *any* wake source: telegram message or MAIN_TICK timeout.
                # Timeout still lets us periodically check mailbox + pending buffer
                # even when no telegram message arrives.
                poller.event.wait(timeout=MAIN_TICK)
                poller.event.clear()

                messages, current_offset = poller.drain()
                state["telegram_offset"] = current_offset

                reap_executors(state)
                synthetic = read_mailbox(state)
                synthetic += read_synthetic_inbox()

                if time.time() - last_watcher_sweep >= WATCHER_SWEEP_INTERVAL:
                    supervise_watchers(state)
                    last_watcher_sweep = time.time()

                buffer = state.get("pending_buffer", [])
                batch = buffer + synthetic + messages
                state["pending_buffer"] = []

                if not batch:
                    write_state(state)
                    continue

                stdout, _ = run_agent(state["active_agent"], batch, state)
                tokens = parse_tokens(stdout)
                handle_tokens(tokens, state)

                write_state(state)

            except KeyboardInterrupt:
                raise
            except Exception as e:
                log_event("loop_error", error=str(e))
                time.sleep(5)
    except KeyboardInterrupt:
        log_event("harness_stop", reason="keyboard")
        print("\nHarness stopped.")
        poller.stop()


if __name__ == "__main__":
    main()
