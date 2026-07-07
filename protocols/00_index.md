# Bismuth Protocols

This folder contains the modular behavior protocols for Bismuth. The goal is to replace the monolithic prompt folder with a set of smaller documents that can be loaded by mode, task, and tool need.

## Loading map — hot and cold

The harness assembles each mode's system prompt as: `soul.md` + mode prompt (`prompts/<mode>.md`) + that mode's **hot** protocols + skills. **Cold** protocols stay on disk; the mode prompt carries their trigger + pointer, and Bismuth reads them on demand when the trigger fires (see the Context Management Protocol). Keep this table in sync with `PROTOCOLS_BY_MODE` in `harness.py`.

- **assistant** — hot: 01–08, 16, 17 · cold: 09 reminders, 10 watchers, 12 skills, 13 project creation
- **coffeechat** — hot: 01, 03–08, 14, 16, 17 · cold: 10 watchers, 12 skills
- **executor** — hot: 01, 04, 05, 11, 19
- **evaluation** — runs manually in the CLI; its prompt points at 15 and 18 directly.

Prompts carry identity and judgment; protocols carry the exact contracts. Protocol changes go through 18 (propose → Janhavi approves).

## Core protocols

- `01_memory_structure_protocol.md` - required memory files and folders.
- `02_memory_update_protocol.md` - where information goes while chatting.
- `03_janhavi_operating_protocol.md` - how Bismuth should interact with Janhavi.
- `04_context_management_protocol.md` - how Bismuth reads, holds, compresses, and avoids context waste.

## Runtime protocols

- `05_tool_usage_protocol.md` - available tools, when to use them, and how to minimize waste while maximizing quality.
- `06_mode_switching_protocol.md` - assistant / coffeechat switching.
- `07_executor_delegation_protocol.md` - how to spawn worker agents and handle their messages.
- `08_synthetic_message_protocol.md` - how harness and watcher messages arrive.
- `09_reminder_runtime_protocol.md` - daily reminders and recurrence behavior.
- `10_watcher_protocol.md` - proactive background sensors.

## Growth and project protocols

- `11_bismuth_code_writing_protocol.md` - how Bismuth writes new code and updates its own code.
- `12_skill_growth_protocol.md` - how Bismuth collects skill badges without becoming messy.
- `13_project_creation_protocol.md` - when and how projects are created.
- `14_coffeechat_protocol.md` - open project thinking mode.
- `15_evaluation_protocol.md` - weekly evaluation of Janhavi's week and of Bismuth itself.
- `16_session_lifecycle_protocol.md` - startup, topic shifts, resets, and endings.
- `17_bismuth_janhavi_image_thinking_protocol.md` - thinking with Janhavi in images and drawings.
- `18_protocol_update_protocol.md` - how Bismuth proposes changes to its own protocols.
- `19_executor_operating_protocol.md` - how a worker agent does its task: work rules, mailbox, finishing.
