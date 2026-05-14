# Bismuth v2 — Restructure Plan

Source doc: the v2 architecture brief (three-agent system: assistant, coffeechat, executor) supersedes the current four-agent pipeline.

This file is the working plan. We pick one chunk at a time, get explicit approval, then execute. Detailed prompt content is left to the implementation pass for each prompt.

---

## Two memory locations to keep in sync

- `bismuth/memory/` — **template** (committed; what a fresh user would see).
- `../bismuth-memory/` — **actual personal data; do not lose anything.**

Every structural change must be mirrored in both. For the actual one we move/rename and only delete after explicit verification.

---

## Decisions captured so far

- Global `tracking.md`: keep at root, tag entries with `<project:NAME>...</project:NAME>` so evaluation can split. Per-project `tracking.md` files get folded into the global one with the tag, then deleted.
- Calendar polling interval: **1 hour**.
- "Multi-session" coffeechat is automatic — files are the state, no extra machinery.
- Evaluation agent (`agents/evaluation.py`, `prompts/evaluation.md`) stays untouched.
- No migration script — restructure is manual, by checklist. Janhavi or a subagent will execute.
- File tool is unnecessary — `terminal` already covers read/write/search.
- `deferred-todo.md` → rename to `someday-maybe.md`. Per-project ones fold into the global with `<project:NAME>` tag.

## Decisions still open

- Executor parallelism cap (suggest 3).
- Tag syntax confirm: `<project:seldon>...</project:seldon>` vs `#project:seldon`.
- `MOOD.md` vs `mood.md` casing.
- A handful of memory extras flagged in `MEMORY_RESTRUCTURE_STEPS.md`.

---

## Chunk A — Memory restructure (both locations)

Detailed file-by-file checklist lives in `MEMORY_RESTRUCTURE_STEPS.md`. Execute manually with eyes on each step.

## Chunk B — New tools

- `tools/calendar.py` — Google Calendar wrapper: `create_event`, `list_events`, `delete_event`, `search_events`.
- `tools/image.py` — `save_image`, `describe_image` (Claude vision).
- Keep all existing tools.

## Chunk C — Harness (`harness.py` at repo root)

- One long-running process, always-on Telegram polling.
- Default agent = assistant. Switches to coffeechat on instruction; back to assistant on exit.
- Buffers messages during agent switches.
- Spawns executor as a background subprocess (parallel to harness).
- Mechanism for executor → janhavi questions (mailbox file or pipe).
- Calendar poll every 1 hour; due events injected to assistant as synthetic messages.
- `fcntl` file locks so concurrent writers don't corrupt shared files.
- Reads project list from `memory/projects/` directly.
- `config.yaml` slimmed to `env:` + `memory_path:` only.

## Chunk D — Prompts (rewrite one at a time)

- `prompts/assistant.md` — new (merges capture + clarify; adds mood + calendar + switching).
- `prompts/coffeechat.md` — rewrite (broader project-steward scope).
- `prompts/executor.md` — new (short, task-focused, autonomous).

Content drafted in its own pass per prompt.

## Chunk E — Retire old code

After C+D land and we've tested the new system:

- Delete `agents/capture.py`, `agents/clarify.py`, `agents/coffeechat.py`, `agents/project.py`.
- Delete `prompts/capture.md`, `prompts/clarify.md`, `prompts/project.md`.
- Untouched: `agents/evaluation.py`, `prompts/evaluation.md`.
- Update `run.sh` to launch `harness.py`.
- Update `README.md` to describe the 3-agent model.

## Chunk F — Auth + setup

- One-time Google Calendar OAuth (`python tools/calendar.py --auth`), token in `~/.config/bismuth/`. Document in `setup.sh`.

---

## Recommended execution order

A (memory restructure) → B (tools) → C (harness skeleton) → D (prompts, one at a time, test against harness) → cutover smoke test → E (retire old) → F (auth/setup polish).
