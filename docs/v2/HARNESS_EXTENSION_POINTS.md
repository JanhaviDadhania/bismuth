# Harness extension points — design spec (Part B)

This is the implementation spec for Part B. Part A (skill files) is already
live. This document supersedes the earlier draft after a design audit that
surfaced 12 issues — fixes are folded into the sections below.

## Why this exists

The assistant should be able to extend its own input sources (camera, mic,
screen, filesystem watchers, MQTT subscribers, etc.) without editing
`harness.py`. The agent must not edit `harness.py` because a syntax or logic
bug there bricks the only process inside which the agent can run — a bootstrap
deadlock with no recovery path.

Instead, the harness exposes two stable extension surfaces:

1. A **synthetic inbox** directory that any process can drop text files into.
2. A **watcher supervisor** that keeps long-running watcher scripts alive.

New input sources become "write a script in a known directory" rather than
"modify the router."

**Telegram stays inside `harness.py` as `TelegramPoller`.** It's the
conversational lifeline and needs sub-second wake-up via a `threading.Event`.
The watcher pattern adds up to `MAIN_TICK` seconds of latency, which is fine
for sensors and webhooks but not for live chat.

---

## B1. Synthetic-inbox directory

A directory that any process can drop text files into. On each main-loop tick,
the harness reads those files, treats each as a synthetic message, and
deletes them.

### Constants

```python
SYNTHETIC_INBOX = HARNESS_DIR / "synthetic_inbox"
MAX_SYNTHETIC_MESSAGE = 10_000   # chars; longer messages get truncated
MAX_FILES_PER_TICK = 20          # cap drain to prevent prompt-bomb on crash-loop
```

### `init_dirs()` additions

```python
SYNTHETIC_INBOX.mkdir(parents=True, exist_ok=True)
```

### Drain function

```python
def read_synthetic_inbox() -> list[str]:
    """Drain text files from SYNTHETIC_INBOX. Caps file count + message size.
    Files are consumed (deleted) after read."""
    out = []
    try:
        files = [f for f in SYNTHETIC_INBOX.iterdir()
                 if f.is_file() and f.name.endswith(".txt")]
    except FileNotFoundError:
        return []
    # Chronological order — watchers don't need to encode time in filenames
    files.sort(key=lambda f: f.stat().st_mtime)

    for f in files[:MAX_FILES_PER_TICK]:
        try:
            text = f.read_text()
            original_len = len(text)
            if original_len > MAX_SYNTHETIC_MESSAGE:
                text = text[:MAX_SYNTHETIC_MESSAGE] + \
                    f"\n...[truncated; original {original_len} chars]"
                log_event("synthetic_msg_truncated", file=f.name, len=original_len)
            out.append(text.strip())
            f.unlink()
        except Exception as e:
            log_event("synthetic_inbox_read_error", file=f.name, error=str(e))

    if len(files) > MAX_FILES_PER_TICK:
        log_event("synthetic_inbox_throttled",
                  drained=MAX_FILES_PER_TICK,
                  remaining=len(files) - MAX_FILES_PER_TICK)
    return out
```

### Main-loop wiring

Inside `main()` loop, alongside `read_mailbox(state)`:

```python
synthetic = read_mailbox(state)
synthetic += read_synthetic_inbox()
```

(`check_daily_reminder()` is removed from harness — it becomes a watcher; see
day-1 manifest below.)

### Atomic-write contract

**Writers MUST** create `SYNTHETIC_INBOX/<name>.txt.tmp` first, then
`os.rename` to `<name>.txt`. The harness only picks up files ending in `.txt`,
so partial `.tmp` files are ignored. Document this in
`SYNTHETIC_INBOX/README.md`, written by `init_dirs()` the first time.

### Message format convention (not enforced by code)

By convention each message starts with a `[source: ...]` prefix so skill
files can teach the agent how to handle each type:

- `[camera: motion detected at 14:02; snapshot saved at /tmp/cam_x.jpg]`
- `[fs-dropbox: paper.pdf saved at /…/paper.pdf]`
- `[daily reminders] read reminders.md, surface anything due today …`
- `[watcher: <name> is failing — check <log_path>]` (emitted by supervisor itself)

### One-way contract

Watchers **write** to `SYNTHETIC_INBOX` only. They must never read or unlink
files there — the harness owns the drain side. Documented in
`tools/watchers/README.md`.

---

## B2. Watcher supervisor

A directory of long-running scripts. The harness ensures each is running,
restarts crashed ones with backoff, kills orphans cleanly, and surfaces
persistent failures back to the agent.

### Constants

```python
WATCHERS_DIR = BASE_DIR / "tools" / "watchers"
WATCHER_STATE_DIR = HARNESS_DIR / "watcher_state"
WATCHER_SWEEP_INTERVAL = 60        # seconds between supervisor sweeps
WATCHER_BACKOFF_BASE = 30          # seconds; doubled per consecutive crash
WATCHER_BACKOFF_MAX = 1800         # cap at 30 min between restart attempts
WATCHER_HEALTHY_UPTIME = 300       # seconds — uptime needed to reset crash count
WATCHER_FAILURE_NOTIFY_THRESHOLD = 3  # consecutive crashes before notifying agent
```

### State shape

`state["watchers"]` is `{filename: {pid, last_spawn_ts, crash_count, notified}}`.
`default_state()` initializes `"watchers": {}`. The pre-existing
`"last_reminder_check"` field is removed (its logic moves to `daily_reminder.py`).

### `init_dirs()` additions

```python
WATCHERS_DIR.mkdir(parents=True, exist_ok=True)
WATCHER_STATE_DIR.mkdir(parents=True, exist_ok=True)
```

### Boot-time orphan cleanup (run ONCE before main loop)

Watchers are **stateless across harness restarts** — simpler than trying to
preserve them and impossible to get wrong via PID reuse:

```python
def kill_orphan_watchers():
    """On harness boot: kill any leftover watcher processes from a previous
    run, so the supervisor can spawn a clean slate. Watchers are stateless
    across boots — none of them hold work-in-progress."""
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
```

Called once in `main()` after `read_state()`, before the main loop. After
this runs, `state["watchers"]` may still reference dead PIDs — that's fine,
the supervisor's first sweep treats them all as dead and spawns fresh.

### PID-reuse defense

```python
def _pid_is_our_watcher(pid: int, script_name: str) -> bool:
    """Verify pid is alive AND its cmdline references our watcher script.
    Guards against PID reuse by unrelated processes."""
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
        # If ps fails for any reason, fall back to assuming alive
        return True
```

### Supervisor function

```python
def supervise_watchers(state: dict):
    """Ensure every tools/watchers/<name>.py has a live child.
    Restart with exponential backoff on consecutive crashes."""
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

    # 2. For each script, ensure a process is live
    for script in sorted(WATCHERS_DIR.glob("*.py")):
        # Underscore-prefixed files are templates/disabled
        if script.name.startswith("_"):
            continue

        name = script.name
        info = tracked.get(name)

        if info and _pid_is_our_watcher(info["pid"], name):
            continue  # healthy, nothing to do

        # Determine consecutive crash count
        if info:
            uptime = now - info.get("last_spawn_ts", now)
            crash_count = 1 if uptime >= WATCHER_HEALTHY_UPTIME \
                            else info.get("crash_count", 0) + 1
        else:
            crash_count = 0  # first spawn, no backoff

        # Backoff: don't respawn until base * 2^(crashes-1) has passed
        if crash_count > 0 and info:
            backoff = min(
                WATCHER_BACKOFF_BASE * (2 ** max(crash_count - 1, 0)),
                WATCHER_BACKOFF_MAX,
            )
            if now - info["last_spawn_ts"] < backoff:
                continue  # still in backoff window

        # Spawn
        proc = _spawn_watcher(script)
        tracked[name] = {
            "pid": proc.pid,
            "last_spawn_ts": now,
            "crash_count": crash_count,
            "notified": info.get("notified", False) if info else False,
        }
        log_event("watcher_spawned", name=name, pid=proc.pid,
                  crash_count=crash_count)

        # Surface persistent failures back to the agent (once per failure run)
        if (crash_count >= WATCHER_FAILURE_NOTIFY_THRESHOLD
                and not tracked[name]["notified"]):
            _notify_watcher_failure(name)
            tracked[name]["notified"] = True
        # Reset notification flag when the watcher recovers (crash_count = 0)
        if crash_count == 0:
            tracked[name]["notified"] = False


def _spawn_watcher(script: Path) -> subprocess.Popen:
    log_path = HARNESS_DIR / f"watcher_{script.stem}.log"
    state_dir = WATCHER_STATE_DIR / script.stem
    state_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["SYNTHETIC_INBOX"] = str(SYNTHETIC_INBOX)
    env["BISMUTH_BASE"] = str(BASE_DIR)
    env["BISMUTH_MEMORY"] = str(MEMORY_DIR)
    env["WATCHER_STATE_DIR"] = str(state_dir)

    # File handle is dup'd by Popen for the child; parent closes its copy.
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
```

### Main-loop wiring

Sweep on a timer, not every tick:

```python
# inside main() above the while True
last_watcher_sweep = 0.0

# inside the while True, after reap_executors(state):
if now() - last_watcher_sweep >= WATCHER_SWEEP_INTERVAL:
    supervise_watchers(state)
    last_watcher_sweep = now()
```

### Watcher contract (documented in `tools/watchers/README.md`)

A file in `tools/watchers/*.py` is expected to:

1. Be runnable with the project's Python interpreter.
2. Loop indefinitely (or block on its event source).
3. Drop synthetic messages into `os.environ["SYNTHETIC_INBOX"]` using
   atomic writes: `*.txt.tmp` first, then `os.rename` to `*.txt`.
4. Persist any state to `os.environ["WATCHER_STATE_DIR"]` (the harness
   creates this dir per watcher and passes it via env).
5. Log to stderr — captured to `{HARNESS_DIR}/watcher_<name>.log`. Don't
   print to stdout for coordination; use the inbox.
6. Never read from `SYNTHETIC_INBOX`. The harness owns the drain side.
7. Exit non-zero only on genuine failure (supervisor backs off + notifies
   agent after 3 consecutive crashes).

Underscore-prefixed filenames (`_template.py`, `_disabled.py`) are ignored
by the supervisor — useful for templates or temporarily-disabled watchers.

### Available environment variables

| Var | What |
|---|---|
| `SYNTHETIC_INBOX` | Absolute path. Where watchers drop messages. |
| `BISMUTH_BASE` | Absolute path. Repo root. |
| `BISMUTH_MEMORY` | Absolute path. Memory root (where projects/, mood.md etc. live). |
| `WATCHER_STATE_DIR` | Absolute path. Per-watcher persistent state dir. |

---

## B3. Placeholders in `_substitute()`

Add to `_substitute()` so skills/tools can reference these paths:

```python
.replace("{SYNTHETIC_INBOX}", str(SYNTHETIC_INBOX))
.replace("{WATCHERS_DIR}", str(WATCHERS_DIR))
```

---

## B4. Prompt-side awareness — section 8 addition

Add this paragraph to section 8 of both `prompts/assistant.md` and
`prompts/coffeechat.md`, after the "Adding a new skill" subsection:

> **Adding a proactive input source.** When the new capability involves
> *sensing the outside world on its own* (camera, mic, sensor, file watcher,
> webhook, calendar) — not just an on-demand tool you reach for — also write
> a **watcher script** in `{WATCHERS_DIR}` that drops synthetic messages
> into `{SYNTHETIC_INBOX}`. Start by copying `_template.py`. The harness will
> auto-spawn it on its next sweep (within 60s).
>
> Default to skill-only. Only set up a watcher when janhavi explicitly says
> "tell me when…", "alert me if…", "watch for…", or similar proactive
> phrasing. When unsure, ask her via Telegram before creating a watcher —
> watchers run forever and can spam if misbehaving.

---

## Day-1 manifest

Files added in this PR:

```
harness.py                            # edited per B1, B2, B3
prompts/assistant.md                  # section 8 addition per B4
prompts/coffeechat.md                 # section 8 addition per B4

tools/
  watchers/
    README.md                         # watcher contract, env vars, examples
    _template.py                      # underscore-prefixed; not auto-run
    daily_reminder.py                 # migrated from harness.check_daily_reminder
    fs_dropbox.py                     # new: file-drop input channel
```

Auto-created at first boot:

```
{HARNESS_DIR}/
  synthetic_inbox/
    README.md                         # atomic-write contract reminder
  watcher_state/
    daily_reminder/
      state.json                      # {"last_fired": "YYYY-MM-DD"}
    fs_dropbox/
      seen.json                       # if needed
```

### Day-1 watcher: `daily_reminder.py`

Replaces `check_daily_reminder()` in `harness.py`. Migration:
- Remove `check_daily_reminder()` function (lines ~390-403).
- Remove `REMINDER_TIME` constant from harness.
- Remove `state["last_reminder_check"]` from `default_state()`.
- Remove the `synthetic += check_daily_reminder(state)` call in `main()`.

Watcher logic:

```python
# tools/watchers/daily_reminder.py
import os, json, time, uuid
from datetime import datetime, time as dtime
from pathlib import Path

INBOX = Path(os.environ["SYNTHETIC_INBOX"])
STATE = Path(os.environ["WATCHER_STATE_DIR"]) / "state.json"
REMINDER_TIME = dtime(9, 0)
POLL_INTERVAL = 60  # check every minute

def load_last_fired() -> str:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text()).get("last_fired", "")
        except Exception:
            return ""
    return ""

def save_last_fired(date: str):
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"last_fired": date}))
    tmp.rename(STATE)

def drop_message(text: str):
    name = f"daily_reminder_{uuid.uuid4().hex}.txt"
    tmp = INBOX / (name + ".tmp")
    tmp.write_text(text)
    tmp.rename(INBOX / name)

if __name__ == "__main__":
    while True:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        if load_last_fired() != today and now.time() >= REMINDER_TIME:
            drop_message(
                "[daily reminders] read reminders.md, surface anything due "
                "today or coming up, and handle any LAST OF SERIES entries."
            )
            save_last_fired(today)
        time.sleep(POLL_INTERVAL)
```

### Day-1 watcher: `fs_dropbox.py`

```python
# tools/watchers/fs_dropbox.py
import os, time, uuid
from pathlib import Path

INBOX = Path(os.environ["SYNTHETIC_INBOX"])
MEMORY = Path(os.environ["BISMUTH_MEMORY"])
DROPBOX = Path.home() / "bismuth-dropbox"
RECEIVED = MEMORY / "_dropbox_received"
POLL_INTERVAL = 5
STABILITY_DELAY = 2  # seconds — wait this long to confirm file isn't mid-write

def drop_message(text: str):
    name = f"fs_dropbox_{uuid.uuid4().hex}.txt"
    tmp = INBOX / (name + ".tmp")
    tmp.write_text(text)
    tmp.rename(INBOX / name)

def process_file(f: Path):
    initial_size = f.stat().st_size
    time.sleep(STABILITY_DELAY)
    if not f.exists() or f.stat().st_size != initial_size:
        return  # still being written or vanished; try again next poll

    target = RECEIVED / f.name
    counter = 0
    while target.exists():
        counter += 1
        target = RECEIVED / f"{f.stem}_{counter}{f.suffix}"
    try:
        f.rename(target)
    except OSError:
        return  # file might have been moved by another process
    drop_message(f"[fs-dropbox: {f.name} saved at {target}]")

if __name__ == "__main__":
    DROPBOX.mkdir(parents=True, exist_ok=True)
    RECEIVED.mkdir(parents=True, exist_ok=True)
    while True:
        for f in DROPBOX.iterdir():
            if f.is_file() and not f.name.startswith("."):
                process_file(f)
        time.sleep(POLL_INTERVAL)
```

### Day-1 watcher: `_template.py`

```python
# tools/watchers/_template.py
# Underscore prefix = ignored by supervisor. Copy to <name>.py to enable.
#
# Contract:
#   - Loop forever, or block on your event source.
#   - Write to SYNTHETIC_INBOX atomically: *.txt.tmp then rename to *.txt.
#   - Persist state to WATCHER_STATE_DIR if you need any.
#   - Log to stderr (captured to {HARNESS_DIR}/watcher_<name>.log).
#   - Never read from SYNTHETIC_INBOX — the harness owns the drain.
#   - Exit non-zero only on genuine failure (supervisor backs off + notifies).
import os, time, uuid
from pathlib import Path

INBOX = Path(os.environ["SYNTHETIC_INBOX"])

def drop_message(text: str):
    name = f"example_{uuid.uuid4().hex}.txt"
    tmp = INBOX / (name + ".tmp")
    tmp.write_text(text)
    tmp.rename(INBOX / name)

if __name__ == "__main__":
    while True:
        drop_message("[example: heartbeat at " + time.strftime("%H:%M") + "]")
        time.sleep(3600)
```

---

## Acceptance criteria

When Part B is built:

1. `cp tools/watchers/_template.py tools/watchers/example.py` → supervisor
   spawns it on next sweep (within 60s) → `[example: heartbeat at HH:MM]`
   appears in the next agent batch.
2. `kill -9 <example pid>` → supervisor respawns it on next sweep.
   `log.jsonl` shows `watcher_spawned` with `crash_count=1`.
3. Repeated `kill -9` three times within 5 min → fourth respawn delayed by
   ~4 min backoff (30s × 2³); after 3 crashes, a `[watcher: example.py is
   failing repeatedly …]` synthetic message arrives in the agent batch.
4. Watcher survives 5+ min of healthy uptime, then crashes → backoff resets
   to base (30s), no failure notification.
5. `rm tools/watchers/example.py` → next sweep kills its process and removes
   it from `state["watchers"]`.
6. Restart harness (`Ctrl-C`, then re-run) → `kill_orphan_watchers` logs
   killed PIDs; supervisor's first sweep spawns fresh watchers. Exactly one
   copy of each runs.
7. Drop a file into `~/bismuth-dropbox/` → within ~7s, file is moved to
   `bismuth-memory/_dropbox_received/` and `[fs-dropbox: <name> saved at
   <path>]` appears in the agent batch.
8. At 09:00 local time → `[daily reminders] …` appears in the batch.
   `watcher_state/daily_reminder/state.json` reflects today's date.
9. Watcher writes a 100 KB message → harness truncates to 10 KB with a
   `…[truncated; original 102400 chars]` suffix. `synthetic_msg_truncated`
   logged.
10. Crash-looping watcher emits 50 files into inbox before death → harness
    drains 20 per tick, `synthetic_inbox_throttled` logged with `remaining=30`.

---

## Risk register

| Risk | Mitigation |
|---|---|
| Watcher crash-loop spamming logs | Exponential backoff, capped at 30 min |
| PID reuse after long uptime | `_pid_is_our_watcher()` cmdline check via `ps` |
| Orphan watchers after harness crash | `kill_orphan_watchers()` on every boot |
| Watcher writes huge message → token bomb | `MAX_SYNTHETIC_MESSAGE` truncation |
| Crash-loop file flood → prompt bomb | `MAX_FILES_PER_TICK` drain cap |
| Healthy watcher penalized by stale crash count | 5-min uptime resets `crash_count` |
| Silent persistent failure | Synthetic-message notification after 3 crashes |
| Watcher concurrent file write race | Atomic `.txt.tmp` → `rename` contract |
| Watcher reads inbox → races with drain | Contract: writers never read inbox |
| Two harness instances → duplicate spawn | Pre-existing; out of Part B scope |

---

## Explicitly NOT in scope

- **Self-restart** of the harness (`os.execv`). Not needed — watchers and
  skills both auto-load without restart.
- **Upstream pull / git auto-update.** Single-user repo; manual `git pull`
  is enough.
- **Agent edits to `harness.py`, `assistant.md`, `coffeechat.md`.** Forbidden;
  the extension points eliminate the reason to want to.
- **Watcher-to-watcher coordination.** Each watcher is independent. If they
  need to share state, do it via `bismuth-memory/` files or via the inbox
  channel.
- **Inotify / kqueue / fsevents.** Filesystem watchers poll. Simpler, no
  platform-specific deps. Acceptable latency.

---

## Implementation order

1. `init_dirs()` adds `SYNTHETIC_INBOX`, `WATCHER_STATE_DIR`, and
   `WATCHERS_DIR` creation. Write the two README files.
2. Add `kill_orphan_watchers()`; wire it into `main()` after `read_state()`.
3. Add `read_synthetic_inbox()` + main-loop wiring + the size/count caps.
4. Add `_pid_is_our_watcher()`, `_spawn_watcher()`, `_notify_watcher_failure()`,
   `supervise_watchers()`; wire into main loop with sweep timer.
5. Add `{SYNTHETIC_INBOX}` and `{WATCHERS_DIR}` to `_substitute()`.
6. Remove `check_daily_reminder()`, `REMINDER_TIME`, the
   `"last_reminder_check"` field, and the call site in `main()`.
7. Write `tools/watchers/_template.py`, `daily_reminder.py`, `fs_dropbox.py`,
   `README.md`.
8. Add the section-8 paragraph to `prompts/assistant.md` and
   `prompts/coffeechat.md`.
9. Smoke test against acceptance criteria 1-10.
