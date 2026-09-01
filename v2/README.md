# bismuth v2 — the runtime

Two jobs: **nothing she says is lost**, and **she can get it back.**

The behaviour is not in this code. It is in `prompts/v2/main_agent.md` and
`prompts/v2/subagent.md`; this package is the plumbing that carries messages,
spawns workers, and writes the record. Design doc: `docs/V2_ARCHITECTURE.md` —
every module maps to a numbered section of it.

## Running it

```sh
python3 -m v2 check            # preflight — config, prompts, memory
python3 -m v2 status           # queue, tasks, session, others/, trace health
python3 -m v2 destinations     # exactly what the agent is told exists
python3 -m v2 serve            # the real thing: Telegram in and out
```

**Before `serve` works you need a second Telegram bot token.** v1 and v2 cannot
both long-poll `getUpdates` on one token — two consumers of one offset steal
each other's messages. Create a second bot with @BotFather and put the token in
`config.yaml` under `v2.telegram_bot_token`, or in `BISMUTH2_TELEGRAM_BOT_TOKEN`.

## Testing it without Telegram, and without touching real memory

```sh
export BISMUTH2_MEMORY_DIR=/tmp/memtest
export BISMUTH2_RUNTIME_DIR=/tmp/rttest
python3 -m v2 feed "this is regarding the mirror. add a next todo to …"
```

`feed` runs one note through the **real** main agent and **real** sub-agents,
prints what would have been sent to her instead of sending it, and then keeps
draining sub-agent results until the work settles. Everything else — routing,
tasks, the trace, the board — behaves exactly as in `serve`.

`python3 -m pytest tests/test_v2.py -q` covers the contracts that must not
break quietly: seq gaplessness, park-before-ask ordering, the invented-
destination guard, `done`-is-an-event, and the sub-agent's terminal statuses.
No test spends money on `claude -p`.

## The modules

| File | Section | What it is |
|---|---|---|
| `trace.py` | §5 | append-only JSONL, `seq` under the append lock |
| `state.py` | §6 | tier 1 `state.json`; the turn queue lives here |
| `tasks.py` | §4.8 | the live list, folded from the trace |
| `ingest.py` | §4.2 | long-poll → durable spool → offset moves last |
| `archive.py` | §4.1 | audio to `bismuth-audio`, off the critical path |
| `destinations.py` | §4.6 | the `DESTINATIONS` block the agent routes against |
| `mainagent.py` | §4.5 | `claude -p`, one session, `--tools ""`, intents as JSON |
| `intents.py` | §4.8 | performs intents, writes a trace event for each |
| `subagent.py` | §4.9 | the stripped spawn; three terminal statuses |
| `runtime.py` | §4 | the loop, boot reconciliation, sessions, concurrency |
| `board_sections.py` | §4.12 | Tasks, `others/`, receipts — added to `tools/board.py` |
| `gitsync.py` | — | the runtime owns git for `bismuth-memory` |

## Measured costs

One simple note, end to end: **main agent turn ~$0.08** (≈7k tokens of context,
3.5% of the window) plus **one sub-agent ~$0.04**. So roughly **$0.12 a note**,
and about 28 notes before the 40% session reset. The sub-agent spawn prefix is
5,063 tokens against a default `claude -p`'s 27,398.

## What is not built

- **Nothing verifies a sub-agent's claim** (issue #18). The prompt makes it read
  its own write back, which catches the "reported done, wrote nothing" case, but
  no independent check exists.
- **TTS voice replies** need `ffmpeg` on the path; without it a voice reply
  falls back to text rather than failing.
- **`bismuth-audio` must exist as a git repo** for pushes to happen. Until it
  does, audio accumulates locally and the trace records that, which is the
  intended failure mode — a note is never blocked by the archive.
