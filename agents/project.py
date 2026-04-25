"""
Project Agent
Picks up tasks from memory/<project_name>/agents_nexttodo.md and works through them
by calling `claude -p`. No Anthropic API key needed.

Usage:
  python agents/project.py <project_name>
  python agents/project.py --general

Run without capture agent — project agent polls Telegram directly for replies.
"""

import os
import sys
import argparse
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import BASE_DIR, MEMORY_DIR, load_config


def _load_env():
    """Load env vars from config.yaml into the process environment."""
    env = load_config().get("env", {})
    for key, value in env.items():
        if value:
            os.environ.setdefault(key, str(value))


def build_message(project_name: str, general: bool) -> tuple[str, Path, Path, Path]:
    template_text = (BASE_DIR / "prompts" / "project.md").read_text()
    telegram_cli = BASE_DIR / "tools" / "telegram_cli.py"

    if general:
        system = (
            template_text
            .replace("memory/{project_name}/", f"{MEMORY_DIR}/")
            .replace("{project_name}", project_name)
        )
        nexttodo_path = MEMORY_DIR / "agents_nexttodo.md"
        pending_path  = MEMORY_DIR / "pending_questions.md"
    else:
        system = (
            template_text
            .replace("{project_name}", project_name)
            .replace("memory/", f"{MEMORY_DIR}/")
        )
        nexttodo_path = MEMORY_DIR / project_name / "agents_nexttodo.md"
        pending_path  = MEMORY_DIR / project_name / "pending_questions.md"

    capture_path = MEMORY_DIR / "capture.md"

    user_message = f"""{system}

---

To send Telegram messages to janhavi, use the Bash tool:
  python3 {telegram_cli} "your message here"

---

Work through all tasks in {nexttodo_path}."""

    return user_message, nexttodo_path, pending_path, capture_path


def is_done(nexttodo_path: Path) -> bool:
    if not nexttodo_path.exists():
        return True
    lines = [l.strip() for l in nexttodo_path.read_text().splitlines()
             if l.strip() and l.strip().startswith("-")]
    if not lines:
        return True
    return all("[KEEP]" in l for l in lines)


def has_pending(pending_path: Path) -> bool:
    return pending_path.exists() and bool(pending_path.read_text().strip())


def wait_for_reply(capture_path: Path) -> None:
    """Poll Telegram directly (long-poll 30s) until a reply arrives, then write it to capture.md."""
    from tools.telegram import get_updates

    print("\n[project-agent] Waiting for your Telegram reply...")
    while True:
        result = get_updates(long_poll=30)
        if not result.get("success"):
            print(f"[project-agent] Telegram poll error: {result.get('error')} — retrying...")
            continue

        messages = [m for m in result.get("messages", []) if m and m.get("text")]
        if not messages:
            continue  # timeout with no messages, poll again

        # Write messages to capture.md for the next claude session to read in Step 0
        with open(capture_path, "a") as f:
            for i, msg in enumerate(messages, 1):
                f.write(f"{i}. {msg['text']}\n")

        print(f"[project-agent] Reply received — resuming.")
        return


def run_claude(user_message: str) -> int:
    result = subprocess.run(
        ["claude", "-p", user_message, "--dangerously-skip-permissions"],
        cwd=str(BASE_DIR),
    )
    return result.returncode


def run(project_name: str, general: bool = False):
    _load_env()
    user_message, nexttodo_path, pending_path, capture_path = build_message(project_name, general)

    iteration = 0
    while True:
        iteration += 1
        print(f"\n[project-agent] Round {iteration} — running claude session...")

        rc = run_claude(user_message)
        if rc != 0:
            print(f"[project-agent] claude -p exited with code {rc}")

        if is_done(nexttodo_path):
            print("[project-agent] All tasks done or kept. Exiting.")
            break

        if has_pending(pending_path):
            wait_for_reply(capture_path)
            # Loop: next claude session reads reply from capture.md in Step 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Project Agent")
    parser.add_argument("project_name", nargs="?", help="Project name")
    parser.add_argument("--general", action="store_true",
                        help="Run on general memory/ directory (no project subfolder)")
    args = parser.parse_args()

    if args.general:
        print("Project agent started for: general (memory/)")
        run("general", general=True)
        print("Project agent done: general")
    elif args.project_name:
        print(f"Project agent started for: {args.project_name}")
        run(args.project_name)
        print(f"Project agent done: {args.project_name}")
    else:
        parser.print_help()
        sys.exit(1)
