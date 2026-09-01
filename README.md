# bismuth

<p align="center"><img width="300" height="300" alt="Bismuth" src="./pngegg.png" /></p>

Janhavi speaks into her phone, and a thing she trusts puts it in the right
place, tells her it did, and can find it again when she asks.

**Two jobs, and only two.** Nothing she says is lost. She can get it back.

This is v2. v1 was an assistant, a brainstorming partner and a worker; v2 is
capture and retrieval, and the brainstorming partner has moved out. That is a
deliberate narrowing — every component removed is one that cannot fail.

## Run it

```sh
./run.sh                  # preflight, then serve
python3 -m v2 status      # queue, tasks, others/, session, trace health
open ~/bismuth-memory/board.html
```

Needs a Telegram bot token in `config.yaml` under `v2.telegram_bot_token`, and
`~/bismuth-memory` as a git repo. `python3 -m v2 check` says what is missing.

## How it works

```
  phone (Telegram voice note)
        │  long-poll, spool to disk, THEN advance the offset
        ▼
  ┌───────────────────────────────────────────────┐
  │  MAIN AGENT — one session, one turn, NO TOOLS │
  │  it decides; it never does                    │
  └───┬──────────────┬──────────────┬─────────────┘
      │ reply        │ task list    │ sub-agents (claude -p, stripped)
      ▼              ▼              ▼ all writes
   Telegram       board        ~/bismuth-memory
        └──────── TRACE (append-only, never rotated) ────────┘
```

The main agent runs with `--tools ""`, so it *cannot* do the work itself — even
a one-line append is delegated to a sub-agent with a self-contained
instruction. Sub-agents have four tools, no identity, and three ways to end:
`done`, `needs_input`, `failed`. Only the main agent ever talks to her.

The trace is the single source of truth. The task list and the board are
projections of it, so they cannot drift.

## Where things are

| Path | What |
|---|---|
| `prompts/v2/` | **the behaviour** — main agent, sub-agent, and both schemas |
| `v2/` | the runtime (see `v2/README.md` for the module map) |
| `docs/V2_ARCHITECTURE.md` | what it is, component by component |
| `docs/V2_REQUIREMENTS.md` | every decision, dated, with the reasoning |
| `tools/board.py` | the memory tree as one infinite canvas |
| `tools/transcribe.py` | faster-whisper, as a subprocess |
| `TESTS.md` | the smoke corpus |

After the runtime stripping, `prompts/v2/main_agent.md` and
`prompts/v2/subagent.md` are the *only* behavioural content in the system. No
skills, no protocols, no MCP. If you want to change how Bismuth behaves, that
is where you go.

## v1

Gone from this branch: the harness, protocols, watchers, the mailbox, modes,
skills, the synthetic inbox. `git log --diff-filter=D --name-only` finds them;
they are in this branch's history, and most are also on `main`.
