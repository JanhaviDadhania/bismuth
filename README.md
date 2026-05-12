
<p align="center"><em>We have been writing code word by word, doing one thing at a time like it's 2015 and still have patience. No we don't. We lost it at the beginning of 2026, right around when claude started finishing our sentences better than us</em></p>

<p align="center"><img width="300" height="300" alt="Bismuth" src="./pngegg.png" /></p>

<p align="center"><em>plus, Everybody is making their personal agent now. I didn't want to be the one left behind. But I also didn't want it to be another claude+chat. So I stayed up a few nights and made Bismuth. You just fork and setup this repo to have your own bismuth.</em></p>

<p align="center"><em>No it doesn't do your dishes. It's a software agent, calm down. But it does check your calendar and find your next free slot, send emails for you, post on Instagram for you, remember everything you've ever told it, write code, browse the web, and honestly after 5 days it is going to know you schedule better than you do.</em></p>

<p align="center"><em>As you start talking to bismuth, it stores everything it know about you in a diary. In memory/ folder. My Bismuth's memory lives in a separate private repo, and yours should too. You don't want your diary on public repo.</em></p>

<p align="center"><em>It works. Here's the receipts.</em></p>
<img width="2109" height="1179" alt="bismuthcareditcard" src="https://github.com/user-attachments/assets/75d7b999-bbcf-4a36-b943-60f0c9c73084" />

<p></p>
<p align="center"><em>Here's what's inside. Don't overthink it. Agents do things, tools are how they do things, prompts are what you tell them, memory is what they remember.</em></p>

## Structure

```
home/
├── agents/
│   ├── capture.py        runs continuously, listens to Telegram
│   ├── clarify.py        runs every 1 hour, routes capture.md
│   ├── project.py        run manually per project
│   ├── coffeechat.py     run manually per project for planning
│   └── evaluation.py     run manually once a week
├── tools/
│   ├── telegram.py
│   ├── terminal.py
│   ├── browser.py
│   └── transcribe.py
├── prompts/
│   ├── capture.md
│   ├── clarify.md
│   ├── project.md
│   ├── coffeechat.md
│   └── evaluation.md
├── memory/               created at runtime by the agents
│   ├── capture.md
│   ├── capture/              media files (photos, videos, voice)
│   ├── nexttodo.md
│   ├── delegate.md
│   ├── deferred-todo.md
│   ├── calendar.md
│   ├── tracking.md
│   ├── reference/
│   │   └── register.md
│   ├── project_1_name/
│   │   ├── vision.md
│   │   ├── nexttodo.md
│   │   ├── tracking.md
│   │   └── support/
│   ├── project_2_name/
│   └── ... other projects
├── run.sh
└── config.yaml
```

## Setup

1. Install app dependencies: `brew bundle` (installs Pulsar)
2. Install Python dependencies: `pip install anthropic faster-whisper requests pyyaml`
3. Install browser: `npm install -g silicon-browser && silicon-browser install`
4. Log in to sites once: `silicon-browser --profile silicon open <url>`
5. Fill in `config.yaml` — add `ANTHROPIC_API_KEY`
6. Create `memory/<project>/vision.md` for each project

## Running

```bash
./run.sh                                  # starts capture + clarify
python agents/project.py <project_name>   # run a project agent
python agents/coffeechat.py <project_name>  # run a coffeechat planning session
python agents/evaluation.py              # weekly report
```
