# Bismuth Reminder Runtime Protocol

Basics Start

Reminders are stored in home `reminders.md`.

The daily reminder watcher fires once per day at or after 09:00 local time.

The watcher sends a synthetic message:

```text
[daily reminders] read reminders.md, surface anything due today or coming up, and handle any LAST OF SERIES entries.
```

Bismuth handles the reminder logic after receiving that synthetic message.

Basics End

Reminder Format Start

Each reminder should be one line.

Preferred format:

```md
- YYYY-MM-DD - reminder text
```

The file should be kept sorted by date.

Reminder Format End

Daily Runtime Start

When Bismuth receives `[daily reminders]`, Bismuth must:

1. Read `reminders.md`.
2. Find reminders due today.
3. Find reminders coming up in the next 3 days.
4. Send Janhavi one short Telegram message summarizing due and upcoming reminders.
5. Skip the Telegram message if nothing is due or upcoming.
6. Remove or strike through reminders that are older than today.

Daily Runtime End

Recurring Reminders Start

Bismuth must not invent vague recurring reminder logic.

Default recurrence count is 30.

If Janhavi asks for a recurring reminder, Bismuth must write 30 separate dated entries.

The 30th entry must include:

```text
(LAST OF SERIES - ask Janhavi if she wants another 30)
```

When a `LAST OF SERIES` reminder fires, Bismuth must ask Janhavi if she wants another 30.

Recurring Reminders End

Reminder Creation Start

When Janhavi asks to be reminded, Bismuth must append or insert the reminder in `reminders.md`.

If the date is ambiguous, Bismuth must ask Janhavi.

If the reminder is project-specific, the reminder still lives in home `reminders.md`, but the reminder text may mention the project.

Reminder Creation End

