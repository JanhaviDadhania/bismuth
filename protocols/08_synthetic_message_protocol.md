# Bismuth Synthetic Message Protocol

Basics Start

Synthetic messages are messages created by the harness, watchers, executors, or Telegram preprocessing.

They are not directly typed by Janhavi, but Bismuth must handle them as part of the incoming batch.

Synthetic messages usually begin with square brackets.

Examples:

```text
[daily reminders] read reminders.md...
[executor #abc for project]: DONE - ...
[telegram voice - saved at <path>]: <transcript>
[fs-dropbox: paper.pdf saved at <path>]
[fresh switch - greet janhavi briefly and warmly]
[watcher: name.py is failing repeatedly - ...]
```

Basics End

Purpose Start

Synthetic messages let the runtime inform Bismuth about things that happened outside normal chat.

They are how executors ask questions and report results.

They are how watchers alert Bismuth.

They are how downloaded Telegram media becomes routable text.

They are how daily reminders trigger.

Purpose End

Handling Start

Bismuth must inspect the prefix and route the message according to its source.

Executor question messages must be answered by writing to the answer path in the message.

Executor `DONE` messages should be reported to Janhavi.

Executor `FAILED` messages should be reported to Janhavi.

`[daily reminders]` messages must be handled by the Reminder Runtime Protocol.

`[fresh switch]` messages require a short greeting only.

Telegram voice and audio messages should be routed by transcript. The raw audio should usually expire unless Janhavi asks to keep it.

Telegram photos, videos, and documents should be moved to a permanent home only if they are useful reference material.

Dropbox messages identify files moved from `dropbox/` into `_dropbox_received/`; Bismuth must route them if their purpose is clear.

Watcher failure messages should make Bismuth inspect the watcher log or tell Janhavi if the watcher matters.

Handling End

