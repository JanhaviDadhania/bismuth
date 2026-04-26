<p align="center"><em>your mind is for having ideas, not holding them</em></p>

# bismuth

A GTD agentic system. Five agents, five tools, one memory folder.

## Structure

```
home/
├── agents/
│   ├── capture.py        runs continuously, listens to Telegram
│   ├── clarify.py        runs every 5 minutes, routes capture.md
│   ├── project.py        run manually per project
│   ├── coffeechat.py     run manually per project for planning
│   └── evaluation.py     run manually once a week
├── tools/
│   ├── telegram.py
│   ├── telegram_cli.py
│   ├── terminal.py
│   ├── browser.py
│   └── transcribe.py
├── prompts/
│   ├── capture.md
│   ├── clarify.md
│   ├── project.md
│   ├── coffeechat.md
│   └── evaluation.md
├── memory/               runtime state, created by agents
│   ├── capture.md
│   ├── capture/              media files (photos, videos, voice)
│   ├── nexttodo.md
│   ├── delegate.md
│   ├── deferred-todo.md
│   ├── calendar.md
│   ├── tracking.md
│   ├── reference/
│   │   └── register.md
│   ├── ai_neuroscience/
│   │   ├── vision.md
│   │   ├── nexttodo.md
│   │   ├── tracking.md
│   │   └── support/
│   ├── social_media/
│   └── ... other projects
├── run.sh
└── config.yaml
```

Persistent long-term memory lives in a separate repo: `bismuth-memory/`.

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
