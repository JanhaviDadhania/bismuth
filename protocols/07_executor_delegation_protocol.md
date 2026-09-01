# Bismuth Executor Delegation Protocol

Basics Start

Executors are worker agents. This protocol covers the delegation side: how Bismuth spawns an executor and handles its messages. How an executor itself works lives in the Executor Operating Protocol.

Bismuth should spawn an executor when the task is real work and doing it inline would interrupt conversation: write a script, run research, summarize a document, generate a draft, scrape data, build or test something.

Bismuth should not spawn an executor for tiny memory routing, short answers, or simple reminders.

The harness kills any assistant or coffeechat turn at 3 minutes. Anything that could run long — research, builds, scraping, large reads — must go to an executor, never run inline. A killed turn comes back with a `[system]` timeout notice; on seeing one, delegate the work and reply short. Executors have no such limit.

Basics End

Spawning Start

1. Choose a short `task_id`.
2. Write a full task spec to `{PENDING_TASKS_DIR}/<task_id>.md`.
3. End output with the token:

```text
SPAWN_EXECUTOR:<task_id>:<project>
```

Use `general` as the project if the task is not project-specific.

The harness starts the executor if a slot is free, otherwise it queues the task and starts it when a slot frees.

When Janhavi says "run my tasks" (optionally for a project), read the relevant `nexttodo.md`, take the `@agent` rows, and expand each row into a full task spec — a one-liner is not enough context for an executor. Spawn one executor per task; emit a token for each and let the harness queue the extras.

Task spec format:

```md
# Task: <short title>

## Goal
## Context
## Output
## Notes
```

Task specs must be specific enough that the executor does not need to ask Janhavi for obvious context. Point to files by path instead of pasting them.

Spawning End

Bismuth Side Start

When an executor asks a question, Bismuth answers directly if it has the context, otherwise relays it to Janhavi via Telegram, and writes the reply to the answer path given in the synthetic message.

When an executor reports `DONE` or `FAILED`, Bismuth tells Janhavi briefly. On `FAILED`, offer to inspect the logs.

Bismuth Side End
