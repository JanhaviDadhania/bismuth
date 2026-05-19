#!/usr/bin/env python3
"""
Bash-callable Telegram sender for agents (assistant, coffeechat, executor).

Usage: python3 tools/telegram_cli.py "message text"

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from the environment.
"""

import os
import sys

import requests


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: telegram_cli.py <message>", file=sys.stderr)
        return 1

    text = sys.argv[1]
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set", file=sys.stderr)
        return 1

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=15)
        data = resp.json()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not data.get("ok"):
        print(f"Error: {data.get('description', 'unknown')}", file=sys.stderr)
        return 1

    print(f"Sent (message_id={data['result']['message_id']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
