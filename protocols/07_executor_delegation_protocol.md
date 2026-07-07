# Bismuth Executor Delegation Protocol

Basics Start

Executors are worker agents. This protocol covers both sides: how Bismuth spawns an executor, and how an executor works.

Bismuth should spawn an executor when the task is real work and doing it inline would interrupt conversation: write a script, run research, summarize a document, generate a draft, scrape data, build or test something.

Bismuth should not spawn an executor for tiny memory routing, short answers, or simple reminders.

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

Executor Work Start

The executor reads `{EXEC_DIR}/task.md` first, then the project's `summary.md`, `vision.md`, and `nexttodo.md`.

Work outputs go under the project folder, always inside a fitting subfolder, never loose at the project root. If no fitting subfolder exists, use `reference/`.

If the project is `general`, outputs go under `{MEMORY_DIR}/general/<task_name>/`.

Every file or folder the executor creates must get an entry in the nearest `summary.md`, so the next reader can pick up cleanly.

The executor adapts when things break: try another path, search the error, read the docs. It verifies its work before finishing.

The executor never sends Telegram messages. It talks only through the mailbox.

Executor Work End

Mailbox Start

`{EXEC_DIR}` is harness-owned scratch, for protocol files only. Work outputs must never go there.

| file | purpose | written by |
|---|---|---|
| `task.md` | task spec | harness |
| `status` | `running` / `asking` / `done` / `failed` | executor |
| `question.txt` | question for Janhavi | executor |
| `answer.txt` | the reply | active agent |
| `result_summary.txt` | one-line result | executor |

To ask a question: write `question.txt`, set status to `asking`, poll for `answer.txt`. After reading the answer, delete `question.txt` and `answer.txt` and set status back to `running` — without this cleanup the next question is never relayed. If no answer arrives in 10 minutes, continue with best judgment and note the timeout.

One question at a time. Ask sparingly; try harder first.

Mailbox End

Finishing Start

Done: verify outputs landed, update the nearest `summary.md`, write `result_summary.txt`, set status to `done`, exit.

Failed: write what was tried and what blocked to `result_summary.txt`, set status to `failed`, exit. Partial success is fine — say what worked and what did not.

Finishing End

Bismuth Side Start

When an executor asks a question, Bismuth answers directly if it has the context, otherwise relays it to Janhavi via Telegram, and writes the reply to the answer path given in the synthetic message.

When an executor reports `DONE` or `FAILED`, Bismuth tells Janhavi briefly. On `FAILED`, offer to inspect the logs.

Bismuth Side End
