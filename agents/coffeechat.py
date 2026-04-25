"""
Coffeechat Agent
Guides janhavi through GTD's Natural Planning Model for a project, one phase
at a time, over Telegram. State lives in files; sessions can span days.

Usage: python agents/coffeechat.py <project_name>
"""

import re
import sys
import time
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.telegram import get_updates
from config import BASE_DIR, MEMORY_DIR


def get_current_phase(project_name: str) -> str:
    """Return the name of the current incomplete phase, or 'done' if all complete."""
    base = MEMORY_DIR / "projects" / project_name
    files = [
        ("lore",         base / "lore.md"),
        ("definition",   base / "coffeechat" / "definition.md"),
        ("outcome",      base / "coffeechat" / "outcome.md"),
        ("brainstorm",   base / "coffeechat" / "brainstorm.md"),
        ("organisation", base / "coffeechat" / "organisation.md"),
    ]
    for phase, path in files:
        if not path.exists() or not path.read_text().lstrip().lower().startswith("done"):
            return phase
    return "done"


def extract_section(text: str, name: str) -> str:
    """Extract content between <!-- SECTION: name --> and <!-- END SECTION: name -->."""
    pattern = rf"<!-- SECTION: {re.escape(name)} -->\n(.*?)<!-- END SECTION: {re.escape(name)} -->"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else ""


def build_prompt(project_name: str, phase: str) -> tuple[str, str]:
    """
    Return (system_prompt, phase_prompt) for the given project and phase.

    system_prompt — static base + rules, passed via --system-prompt (cacheable)
    phase_prompt  — phase-specific section only, passed as the user message prefix
    """
    raw = (
        (BASE_DIR / "prompts" / "coffeechat.md")
        .read_text()
        .replace("{project_name}", project_name)
        .replace("memory/", f"{MEMORY_DIR}/")
    )

    base = extract_section(raw, "base")
    rules = extract_section(raw, "rules")
    phase_section = extract_section(raw, phase) if phase != "done" else ""

    system_prompt = f"{base}\n\n---\n\n{rules}"
    return system_prompt, phase_section


def is_complete(project_name: str) -> bool:
    return get_current_phase(project_name) == "done"


def call_claude(project_name: str, incoming: list[str]):
    phase = get_current_phase(project_name)
    system_prompt, phase_section = build_prompt(project_name, phase)
    telegram_cli = BASE_DIR / "tools" / "telegram_cli.py"

    if incoming:
        messages_block = "\n".join(incoming)
        action = (
            f"Continue the coffeechat for project: {project_name}. Current phase: {phase}.\n"
            f"Read the phase file to see what you last asked.\n"
            f"Incoming messages from janhavi:\n{messages_block}\n"
            f"Process each message, update the phase file, send your next question via Telegram, then stop."
        )
    else:
        action = (
            f"Begin or continue the coffeechat for project: {project_name}. Current phase: {phase}.\n"
            f"Read the phase file to see what's already there. If fresh, send your opening question. "
            f"If resuming, reference what's already written and send your next question. Write any updates to disk, then stop."
        )

    user_message = f"{phase_section}\n\n---\n\nTo send Telegram messages to janhavi, use the Bash tool:\n  python3 {telegram_cli} \"your message here\"\n\n---\n\n{action}"

    result = subprocess.run(
        [
            "claude", "-p", user_message,
            "--system-prompt", system_prompt,
            "--dangerously-skip-permissions",
        ],
        cwd=str(BASE_DIR),
    )

    if result.returncode != 0:
        print(f"claude -p exited with code {result.returncode}")


def fetch_messages() -> list[str]:
    result = get_updates(long_poll=30)
    if not result["success"]:
        print(f"Telegram error: {result['error']}")
        return []
    lines = []
    for msg in result["messages"]:
        if "text" in msg:
            lines.append(f"TEXT: {msg['text']}")
        elif "caption" in msg:
            lines.append(f"TEXT: {msg['caption']}")
    return lines


def run(project_name: str):
    if is_complete(project_name):
        return

    # Initial kick — send first question of the current phase
    call_claude(project_name, [])

    if is_complete(project_name):
        return

    # Conversational loop — wait for janhavi's replies
    while True:
        try:
            lines = fetch_messages()
        except Exception as e:
            print(f"Fetch error: {e}. Retrying in 10s...")
            time.sleep(10)
            continue

        if not lines:
            if is_complete(project_name):
                break
            continue

        if is_complete(project_name):
            break

        call_claude(project_name, lines)

        if is_complete(project_name):
            break


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agents/coffeechat.py <project_name>")
        sys.exit(1)

    project_name = sys.argv[1]
    print(f"Coffeechat agent started for: {project_name}")
    try:
        run(project_name)
    except KeyboardInterrupt:
        print("\nCoffeechat agent stopped.")
    print(f"Coffeechat agent done: {project_name}")
