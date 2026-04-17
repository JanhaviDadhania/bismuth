"""
Project Agent
Picks up tasks from memory/<project_name>/nexttodo.md and works through them
by calling `claude -p`. No Anthropic API key needed.

Usage: python agents/project.py <project_name>
"""

import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import BASE_DIR, MEMORY_DIR


def run(project_name: str):
    prompt_template = BASE_DIR / "prompts" / "project.md"
    system = (
        prompt_template.read_text()
        .replace("{project_name}", project_name)
        .replace("memory/", f"{MEMORY_DIR}/")
    )

    telegram_cli = BASE_DIR / "tools" / "telegram_cli.py"

    user_message = f"""{system}

---

To send Telegram messages to janhavi, use the Bash tool:
  python3 {telegram_cli} "your message here"

---

Work through all tasks in {MEMORY_DIR}/{project_name}/agents_nexttodo.md."""

    result = subprocess.run(
        ["claude", "-p", user_message, "--dangerously-skip-permissions"],
        cwd=str(BASE_DIR),
    )

    if result.returncode != 0:
        print(f"claude -p exited with code {result.returncode}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agents/project.py <project_name>")
        sys.exit(1)

    project_name = sys.argv[1]
    print(f"Project agent started for: {project_name}")
    run(project_name)
    print(f"Project agent done: {project_name}")
