<p align="center"><em>your mind is for having ideas, not holding them</em></p>


<p align="center"><em>We have been writing code word by word, doing one thing at a time like it's 2015 and still have patience. No we don't. We lost it at the beginning of 2026, right around when claude started finishing our sentences better than us</em></p>

<p align="center"><img width="300" height="300" alt="Bismuth" src="./pngegg.png" /></p>

<p align="center"><em>plus, Everybody is making their personal agent now. I didn't want to be the one left behind. But I also didn't want it to be another claude+chat. So I stayed up a few nights and made Bismuth. You just fork and setup this repo to have your own bismuth.</em></p>

<p align="center"><em>No it doesn't do your dishes. It's a software agent, calm down. But it does remember everything you've ever told it, surface your reminders every morning, pick up any file you drop in a folder, run research tasks in the background, write code, browse the web, and honestly after 5 days it is going to know your schedule better than you do.</em></p>

<p align="center"><em>As you start talking to bismuth, it stores everything it know about you in a diary. In memory/ folder. My Bismuth's memory lives in a separate private repo, and yours should too. You don't want your diary on public repo.</em></p>

<p align="center"><em>It works. Here's the receipts.</em></p>
<img width="2109" height="1179" alt="bismuthcareditcard" src="https://github.com/user-attachments/assets/75d7b999-bbcf-4a36-b943-60f0c9c73084" />

<p></p>
<p align="center"><em>Here's what's inside. Don't overthink it. Agents do things, tools are how they do things, prompts are what you tell them, memory is what they remember.</em></p>

## Architecture (v2)

Three agents driven by one long-running harness:

- **Assistant** — always-on. Reads every Telegram message, routes to memory, captures mood, replies in your voice. Default agent.
- **Coffeechat** — thinking partner per project. Invoked when you signal you want to think/brainstorm. Hands back to assistant when done.
- **Executor** — does the actual work. Spawned per task, runs in the background (up to 3 concurrent). Writes outputs into memory, asks via mailbox files when stuck.

The **harness** owns Telegram polling (with an on-disk spool so a crash can't lose messages), agent switching, executor lifecycle (with queueing past the cap), watcher supervision, and state persistence. Agents are `claude -p` subprocesses holding resumable sessions; everything they remember lives on disk. `/status` and `/halt` are answered by the harness directly — no LLM call, so they work even when the agent path is broken.

```
home/
├── harness.py            the always-on orchestrator
├── prompts/
│   ├── assistant.md
│   ├── coffeechat.md
│   ├── executor.md
│   ├── evaluation.md     loaded manually in CLI for weekly eval
│   └── skills/           *.md skill files concatenated onto agent prompts
├── tools/
│   ├── telegram_cli.py   send-only Telegram CLI used by agents
│   ├── track_append.py   flock'd append for shared files (tracking.md)
│   ├── transcribe.py     voice → text (faster-whisper); also a CLI
│   ├── tts.py            macOS `say` wrapper
│   ├── r2d2_chirp.py     chirp synth for the robot body
│   └── watchers/         auto-supervised sensors (daily_reminder, fs_dropbox, …)
├── run.sh                starts harness + memory git-sync loop
└── config.yaml           env vars + memory_path (the only two keys read)
```

Memory lives in a separate private repo at `~/bismuth-memory/`:

```
bismuth-memory/
├── nexttodo.md           tagged @janhavi or @agent
├── someday-maybe.md
├── to_read.md
├── mood.md
├── second_order_thoughts.md
├── tracking.md           global, with <project:NAME> tags
├── checklists.md
├── reference/
└── projects/<name>/
    ├── vision.md
    ├── nexttodo.md
    ├── reference/
    └── coffeechat/       (optional session state)
```

Runtime scratch (state, executor mailboxes, telegram spool, logs) lives under `~/bismuth-memory/.harness/` — gitignored in the memory repo; it's scratch, not memory.

Design docs: `docs/v2/V2_PLAN.md`, `docs/v2/HARNESS_DESIGN.md`, `docs/v2/MEMORY_RESTRUCTURE_STEPS.md`. Smoke test corpus: `TESTS.md`.

## Setup

1. Install app dependencies: `brew bundle`
2. Install Python dependencies: `pip install -r requirements.txt`
3. Install browser: `npm install -g silicon-browser && silicon-browser install`
4. Log in to sites once: `silicon-browser --profile silicon open <url>`
5. Copy `config.yaml.example` → `config.yaml` and fill in `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and `memory_path` (your private memory repo). `ANTHROPIC_API_KEY` is optional if `claude login` has been run.
6. In your memory repo, create `projects/<name>/vision.md` for each project (or just tell the assistant to start one).

## Running

```bash
./run.sh                                # starts harness + memory git-sync loop
```

The harness listens on Telegram. Talk to it; it routes, replies, switches to coffeechat when asked, and spawns executors when work needs doing.

Two messages are answered by the harness itself, instantly and without an LLM call:

- `/status` — active agent, session age, executors (running/asking/queued), watcher health.
- `/halt` — kill all executors, clear the queue and buffer, reset to assistant.

### Weekly evaluation

Run manually, once a week, in Claude CLI:

```bash
cd ~/bismuth-memory
claude
# then in Claude: "read ~/bismuth/prompts/evaluation.md and follow those instructions"
```

The evaluation agent reads `evaluation_focus.md` (which it edits itself over time as you express what to track), looks at the past week of `tracking.md` / `mood.md` / `reminders.md` / nexttodos, and runs a short conversation. Session summary lands in `~/bismuth-memory/evaluation/<date>.md`.
