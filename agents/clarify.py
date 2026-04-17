"""
Clarify Agent
Calls `claude -p` every 1 hour to classify and route items from memory/capture.md.
No Anthropic API key needed.
"""

import sys
import time
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import BASE_DIR, MEMORY_DIR

INTERVAL = 1 * 60 * 60  # 1 hour


def run():
    capture_file = MEMORY_DIR / "capture.md"
    if not capture_file.exists() or not capture_file.read_text().strip():
        print("capture.md is empty. Nothing to process.")
        return

    prompt_path = BASE_DIR / "prompts" / "clarify.md"
    system = prompt_path.read_text().replace("memory/", f"{MEMORY_DIR}/")

    telegram_cli = BASE_DIR / "tools" / "telegram_cli.py"

    user_message = f"""{system}

---

To send a Telegram message to janhavi, use the Bash tool:
  python3 {telegram_cli} "your message here"

---

Process {MEMORY_DIR}/capture.md now. Read it, classify every item, route each to the right file, update tracking.md, and clear capture.md."""

    result = subprocess.run(
        ["claude", "-p", user_message, "--dangerously-skip-permissions"],
        cwd=str(BASE_DIR),
    )

    if result.returncode != 0:
        print(f"claude -p exited with code {result.returncode}")
    else:
        print("Clarify run complete.")


if __name__ == "__main__":
    print("Clarify agent started. Running every 1 hour.")
    while True:
        try:
            print("Running clarify...")
            run()
            print("Done. Next run in 1 hour.")
        except KeyboardInterrupt:
            print("\nClarify agent stopped.")
            break
        except Exception as e:
            print(f"Error: {e}. Retrying next cycle.")

        try:
            time.sleep(INTERVAL)
        except KeyboardInterrupt:
            print("\nClarify agent stopped.")
            break
