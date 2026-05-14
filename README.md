<p align="center"><em>your mind is for having ideas, not holding them</em></p>


<p align="center"><em>We have been writing code word by word, doing one thing at a time like it's 2015 and still have patience. No we don't. We lost it at the beginning of 2026, right around when claude started finishing our sentences better than us</em></p>

<p align="center"><img width="300" height="300" alt="Bismuth" src="./pngegg.png" /></p>

<p align="center"><em>plus, Everybody is making their personal agent now. I didn't want to be the one left behind. But I also didn't want it to be another claude+chat. So I stayed up a few nights and made Bismuth. You just fork and setup this repo to have your own bismuth.</em></p>

<p align="center"><em>No it doesn't do your dishes. It's a software agent, calm down. But it does check your calendar and find your next free slot, send emails for you, post on Instagram for you, remember everything you've ever told it, write code, browse the web, and honestly after 5 days it is going to know you schedule better than you do.</em></p>

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

The **harness** owns Telegram polling, agent switching, executor lifecycle, and state persistence. Agents are stateless `claude -p` subprocesses; everything they remember lives on disk.

```
home/
├── harness.py            the always-on orchestrator
├── agents/
│   └── evaluation.py     weekly evaluation (independent of harness)
├── prompts/
│   ├── assistant.md
│   ├── coffeechat.md
│   ├── executor.md
│   └── evaluation.md
├── tools/
│   ├── telegram_cli.py
│   ├── terminal.py
│   ├── browser.py
│   └── transcribe.py
├── run.sh                starts harness + memory git-sync loop
└── config.yaml           env vars + memory_path
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

Runtime scratch (state, executor mailboxes, logs) lives under `~/bismuth-memory/.harness/`.

Design docs: `docs/v2/V2_PLAN.md`, `docs/v2/HARNESS_DESIGN.md`, `docs/v2/MEMORY_RESTRUCTURE_STEPS.md`. Smoke test corpus: `TESTS.md`.

## Setup

1. Install app dependencies: `brew bundle`
2. Install Python dependencies: `pip install anthropic faster-whisper requests pyyaml`
3. Install browser: `npm install -g silicon-browser && silicon-browser install`
4. Log in to sites once: `silicon-browser --profile silicon open <url>`
5. Fill in `config.yaml` — add `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. `ANTHROPIC_API_KEY` is optional if `claude login` has been run.
6. Create `memory/<project>/vision.md` for each project.

## Running

```bash
./run.sh                                # starts harness + memory git-sync loop
python agents/evaluation.py             # weekly report (manual)
```

The harness listens on Telegram. Talk to it; it routes, replies, switches to coffeechat when asked, and spawns executors when work needs doing.
