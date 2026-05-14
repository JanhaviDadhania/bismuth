# Harness Design — bismuth v2

This is the design for `harness.py`. Code comes after we agree on shape.

---

## Core model

- One long-running Python process: `harness.py`.
- LLM agents (assistant, coffeechat, executor) are invoked as **claude subprocesses** via `subprocess.run(["claude", "-p", ...])`. Each invocation = one turn. Between turns the agent isn't running.
- Harness is the only always-on thing. Files on disk are the only memory between turns.
- Only **one** of (assistant, coffeechat) owns Telegram at a time. Executors run in background, never touch Telegram directly.

---

## Main loop

```python
while True:
    messages = telegram_long_poll(timeout=50)   # blocks until message or 50s
    synthetic = read_mailbox()      # executor mailboxes, calendar reminders
    batch = synthetic + messages                # synthetic first so context comes before user
    if not batch:
        continue

    active = state["active_agent"]               # "assistant" or "coffeechat:<project>"
    result = run_agent(active, batch)
    handle_exit_tokens(result)                   # may switch agent, spawn executor, etc.
```

Single-threaded, sequential. Harness polls again only after the current turn finishes and any switching is done. No race between the harness and the active agent.

**Calendar polling** runs on its own 1-hour timer in a background thread; it only writes synthetic messages into a queue that the main loop drains via `read_mailbox()`.

---

## Exit-token protocol

The LLM owns judgment. Harness only does literal regex matching on the **last lines** of the agent's stdout. Tokens are written by the agent.

Recognised tokens (one per line, at end of output):

| Token | Meaning |
|---|---|
| `SWITCH:coffeechat:<project>` | Hand Telegram over to coffeechat for `<project>`. |
| `SWITCH:assistant` | Hand Telegram back to assistant. |
| `SPAWN_EXECUTOR:<task_id>` | Launch executor for task `<task_id>` (task already written to disk by the agent). Agent must include the file path or task content in its disk write before emitting this. |
| `PENDING:<json>` | Messages from this batch the agent didn't process and wants the next agent to see. JSON array of strings. Harness buffers these and prepends to the next agent's first batch. |
| `HALT` | Stop all executors, reset to assistant. Reserved for emergencies. |

Anything else in stdout is the agent's natural-language reply (it sent to Telegram itself using the telegram tool).

---

## State file

`memory/.harness/state.json` — single source of truth for runtime state. Survives restarts. Holds the Telegram offset too (the old `telegram_offset.json` and `telegram_offset.backup.json` files get retired at cutover).

```json
{
  "active_agent": "assistant" | "coffeechat:<project>",
  "telegram_offset": 12345,
  "executors": {
    "<task_id>": {
      "pid": 4567,
      "project": "seldon",
      "started_at": "2026-05-14T10:00:00",
      "status": "running" | "asking" | "done" | "failed"
    }
  },
  "pending_buffer": ["<msg>", "<msg>"]
}
```

**Atomic write + backup** on every state change:
1. Write new state to `memory/.harness/.state.json.tmp`.
2. `fsync` to flush to disk.
3. `os.rename(state.json, .state.json.bak)` — rotates current to backup.
4. `os.rename(.state.json.tmp, state.json)` — installs new state.

Result: on disk we always have one valid `state.json` and one valid `.state.json.bak`. Crash mid-write at worst leaves a stale `.tmp` file (ignored on next start). On startup, harness prefers `state.json`; if missing or unparseable, falls back to `.state.json.bak`.

---

## Switch handoff

User example: you send two messages back-to-back — "switch to seldon coffeechat" + "the new feature I want to talk about is X."

Flow:
1. Harness long-poll returns `[msg1, msg2]`.
2. Active agent = assistant. Harness runs assistant with batch = `[msg1, msg2]`.
3. Assistant sees msg1 is a switch trigger; msg2 isn't for it. Assistant exits with:
   ```
   <any reply text it sent to telegram>
   PENDING:["the new feature I want to talk about is X"]
   SWITCH:coffeechat:seldon
   ```
4. Harness parses tokens. Buffers `PENDING` content. Updates `state.active_agent = "coffeechat:seldon"`. Persists state.
5. Next loop iteration: harness reads buffer, prepends to incoming messages, invokes coffeechat.

Same flow reversed for coffeechat → assistant. The active agent owns the decision of *what was for me vs. what's for the next agent*.

---

## Executors (background, parallel)

- Spawned via `subprocess.Popen(["claude", "-p", ...])` in background — non-blocking.
- Cap: max 3 concurrent. If a 4th is requested, harness queues it.
- Each executor gets a UUID and its own scratch dir (for coordination only — task description, question mailbox, status):
  ```
  memory/.harness/executor_<uuid>/
    task.md         # the task description
    log.jsonl       # what the executor did
    question.txt    # if executor needs to ask something — writes here
    answer.txt      # harness/agent writes the answer here
    status          # one word: running | asking | done | failed
  ```
- Executor has **full read + write access across `memory/`** — it writes its actual work output directly into project dirs, `tracking.md`, etc. The scratch dir is only for harness coordination (task spec, mailbox, status). This way executor results live in main memory naturally; no consolidation step needed.
- **Task organization is the executor's responsibility.** The spawning agent writes a clear task description to `task.md`. The executor decides where outputs go (project `reference/`, `tracking.md` entries, project files) and keeps things tidy. The harness does not arbitrate output location.
- Executor **never touches Telegram directly.** It only communicates via its scratch mailbox.
- Both assistant *and* coffeechat can spawn executors (via `SPAWN_EXECUTOR:` token). Reason: you might want to plot a graph mid-brainstorm without leaving coffeechat.

### Executor → janhavi question mechanism (mailbox files)

When an executor needs to ask something:
1. Executor writes the question to its `question.txt`.
2. Executor writes `asking` to its `status` file.
3. Executor enters a polling loop: every 5 seconds, check `answer.txt`. When it appears, read and continue.
4. Harness's `read_mailbox()` scans all executor dirs each iteration. Any `status=asking` with no answer yet → injects `[executor #<uuid> for <project>]: <question>` as a synthetic message into the active agent's next batch.
5. Active agent (assistant or coffeechat) sees the tagged question. It decides: answer directly from its own knowledge, OR relay to janhavi via Telegram and wait for her reply.
6. When janhavi (or the agent) provides the answer, the agent writes to that executor's `answer.txt` using its file tool.
7. Executor's next poll picks up the answer and resumes.
8. Timeout: if no answer in 10 minutes, executor writes `TIMEOUT` to `answer.txt` itself and continues with best effort.

Tagging each question with the executor UUID prevents confusion when 2-3 executors are asking different things at the same time.

### Executor results

When an executor finishes:
1. It has already written its actual outputs into `memory/` (project dirs, `tracking.md`, etc.).
2. Writes a one-line summary to `result_summary.txt` in its scratch dir and sets `status=done`.
3. Harness sees `status=done` on next tick, injects `[executor #<uuid>]: DONE — <summary>` as a synthetic message to active agent.
4. Active agent tells janhavi.
5. Harness cleans up the scratch dir after a delay (or on next harness start). Actual work outputs in `memory/` stay.

---

## Concurrency / write safety

Race participants:
- Harness writes: `state.json`, executor scratch dirs, `pending_buffer`.
- Active agent (assistant/coffeechat) writes: `nexttodo.md`, `mood.md`, `tracking.md`, project files, executor `answer.txt`.
- Executor writes: anywhere in `memory/` (full read+write), plus its own scratch dir for coordination.

**Rules:**
- Active agent never runs simultaneously with another active agent (single-threaded main loop).
- Active agent vs. executor: both can write to the same files (e.g. `tracking.md`, project `nexttodo.md`). Protected by `fcntl.flock` on every write to shared files. Whichever process gets the lock first writes; the other blocks briefly.
- Harness state file (`state.json`) is only written by the harness, no contention.
- Executor mailbox files (`question.txt`, `answer.txt`, `status`): single-writer per file by convention (executor writes question + status, active agent writes answer). No lock needed.

---

## Calendar reminders

Background thread, every 1 hour:
1. Queries Google Calendar for events due in the next polling window.
2. For each due event, appends a synthetic message to the queue: `[calendar] <title> @ <time> — <description>`.
3. Main loop picks it up via `read_mailbox()` on next iteration.
4. Assistant phrases it in her voice and pings via Telegram.

Reminders thus always pass through the assistant — keeps tone consistent and respects whatever agent is active (coffeechat sees them too and can decide whether to interrupt or let them wait).

---

## Crash recovery

- Each `subprocess.run` is wrapped in `try/except`.
- Non-zero exit → log to `.harness/log.jsonl`, send Telegram: "agent <name> crashed (exit N), restarting." Retry once. Second failure → escalate, set `active_agent = assistant`, alert.
- Executor crash → mark `status=failed`, surface to active agent like a `DONE` event but with failure summary.
- Harness itself crash → on restart, reads `state.json`, resumes with `active_agent`, replays `pending_buffer`. Telegram offset preserved so no message lost.

---

## Kill switch

If janhavi sends `/halt`:
- Harness kills all running executor subprocesses.
- Clears `pending_buffer`.
- Sets `active_agent = assistant`.
- Sends confirmation.

---

## File layout

```
harness.py                         # the entry point
memory/.harness/
  state.json                        # runtime state (includes telegram offset)
  .state.json.bak                   # hidden backup, rotated on every write
  log.jsonl                         # heartbeat + events
  executor_<uuid>/                  # one per executor
    task.md, log.jsonl, question.txt, answer.txt, status, result_summary.txt
```

`.harness/` is gitignored in both bismuth and bismuth-memory (it's runtime scratch, not memory).

`pending_buffer` lives inside `state.json` (not a separate file) so the buffer can't drift out of sync with the active-agent flag.

---

## Resolved decisions

- **Executor question routing** → LLM judgment. Active agent answers directly when it can; only asks janhavi when actually needed.
- **Executor file access** → full read + write across `memory/`. Scratch dir is just for harness coordination (task spec, mailbox, status). `fcntl.flock` on shared file writes prevents corruption when executor + active agent race.
- **Telegram offset** → folded into `state.json`. Existing `telegram_offset.json` + `telegram_offset.backup.json` files retired at harness cutover.
- **State backup** → atomic write + hidden `.state.json.bak` (rotated on every write). On startup, fall back to backup if main file is corrupt.
