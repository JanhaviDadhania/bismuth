# Bismuth Executor Operating Protocol

Basics Start

This protocol is for executor mode: how a worker agent does its task. The spawning side lives in the Executor Delegation Protocol.

Basics End

Work Start

The executor reads `{EXEC_DIR}/task.md` first, then the project's `summary.md`, `vision.md`, and `nexttodo.md`.

Work outputs go under the project folder, always inside a fitting subfolder, never loose at the project root. If no fitting subfolder exists, use `reference/`.

If the project is `general`, outputs go under `{MEMORY_DIR}/general/<task_name>/`.

Every file or folder the executor creates must get an entry in the nearest `summary.md`, so the next reader can pick up cleanly.

The executor adapts when things break: try another path, search the error, read the docs. It verifies its work before finishing.

The executor never sends Telegram messages. It talks only through the mailbox.

Work End

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
