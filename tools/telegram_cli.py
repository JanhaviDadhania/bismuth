#!/usr/bin/env python3
"""
Bash-callable wrapper for telegram send_message.
Used by clarify agent so claude -p can send messages via Bash tool.

Usage: python3 tools/telegram_cli.py "message text"
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.telegram import send_message

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: telegram_cli.py <message>", file=sys.stderr)
        sys.exit(1)

    text = sys.argv[1]
    result = send_message(text)

    if result["success"]:
        print(f"Sent (message_id={result['message_id']})")
    else:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)
