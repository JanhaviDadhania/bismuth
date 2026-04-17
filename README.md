# budee

A GTD agentic system. Four agents, four tools, one memory folder.

## Structure

```
home/
├── agents/
│   ├── capture.py        runs continuously, listens to Telegram
│   ├── clarify.py        runs every 1 hour, routes capture.md
│   ├── project.py        run manually per project
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

## Setup

1. Install app dependencies: `brew bundle` (installs Pulsar)
2. Install Python dependencies: `pip install anthropic faster-whisper requests pyyaml`
3. Install browser: `npm install -g silicon-browser && silicon-browser install`
4. Log in to sites once: `silicon-browser --profile budee open <url>`
5. Fill in `config.yaml` — add `ANTHROPIC_API_KEY`
6. Create `memory/<project>/vision.md` for each project

## Running

```bash
./run.sh                                  # starts capture + clarify
python agents/project.py <project_name>   # run a project agent
python agents/evaluation.py              # weekly report
```
