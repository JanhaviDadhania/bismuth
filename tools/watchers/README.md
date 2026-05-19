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

## Day-1 watchers

- `daily_reminder.py` — fires once per day at 09:00 local, drops the
  `[daily reminders] …` synthetic message. Replaces what used to be a
  hardcoded function inside the harness.
- `fs_dropbox.py` — watches `{BISMUTH_MEMORY}/dropbox/`; routes new files to
  `{BISMUTH_MEMORY}/_dropbox_received/` and notifies the agent.
