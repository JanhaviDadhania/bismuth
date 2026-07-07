# Bismuth Watcher Protocol

Basics Start

Watchers are long-running scripts that sense the outside world and wake Bismuth by sending synthetic messages.

Watchers live in:

```text
tools/watchers/
```

The harness automatically starts every `*.py` watcher that does not begin with `_`.

Files beginning with `_` are ignored and may be used as templates or disabled watchers.

Basics End

When To Create Start

Bismuth may create a watcher only when Janhavi explicitly asks for proactive behavior.

Trigger phrases include:

- tell me when
- alert me if
- watch for
- monitor
- wake me when
- keep checking

If Janhavi asks for a normal one-time action, Bismuth must not create a watcher.

If Bismuth is unsure whether proactive watching is desired, Bismuth must ask Janhavi before creating a watcher.

When To Create End

Watcher Contract Start

Every watcher must:

1. Run an indefinite loop or block on an event source.
2. Write messages to `os.environ["SYNTHETIC_INBOX"]`.
3. Use atomic writes: write `<name>.txt.tmp`, then rename to `<name>.txt`.
4. Persist state in `os.environ["WATCHER_STATE_DIR"]`.
5. Log to stderr.
6. Never read or delete files from `SYNTHETIC_INBOX`.
7. Exit nonzero only on genuine failure.

Watcher Contract End

Message Format Start

Watcher messages should begin with a source prefix:

```text
[source: details]
```

Examples:

```text
[daily reminders] read reminders.md...
[fs-dropbox: paper.pdf saved at /path]
[camera: motion detected at 14:02; snapshot at /tmp/cam.jpg]
```

Message Format End

Failure Handling Start

The harness restarts crashed watchers with exponential backoff.

After repeated crashes, the harness sends a synthetic failure message to Bismuth.

When Bismuth receives a watcher failure message, Bismuth should inspect the watcher log if the watcher matters.

Bismuth should tell Janhavi if the watcher was important and is not functioning.

Failure Handling End

Existing Watchers Start

`daily_reminder.py` fires once per day at or after 09:00 local time.

`fs_dropbox.py` watches home `dropbox/`, moves stable new files to `_dropbox_received/`, and notifies Bismuth.

Existing Watchers End

