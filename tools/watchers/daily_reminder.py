"""
Daily reminder watcher — migrated from the in-harness check_daily_reminder.

Fires once per day at or after REMINDER_TIME (09:00 local). Drops a
"[daily reminders] ..." synthetic message; the agent then reads
reminders.md, surfaces anything due, and handles LAST OF SERIES entries.

State (which day we last fired) lives in WATCHER_STATE_DIR/state.json,
written atomically. Survives watcher restarts and harness restarts.
"""

import json
import os
import sys
import time
import uuid
from datetime import datetime, time as dtime
from pathlib import Path

INBOX = Path(os.environ["SYNTHETIC_INBOX"])
STATE = Path(os.environ["WATCHER_STATE_DIR"]) / "state.json"
REMINDER_TIME = dtime(9, 0)
POLL_INTERVAL = 60  # check every minute

MESSAGE = (
    "[daily reminders] read reminders.md, surface anything due today or "
    "coming up, and handle any LAST OF SERIES entries."
)


def load_last_fired() -> str:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text()).get("last_fired", "")
        except Exception as e:
            print(f"daily_reminder: state read failed: {e}", file=sys.stderr)
            return ""
    return ""


def save_last_fired(date: str):
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"last_fired": date}))
    tmp.rename(STATE)


def drop_message(text: str):
    name = f"daily_reminder_{uuid.uuid4().hex}.txt"
    tmp = INBOX / (name + ".tmp")
    tmp.write_text(text)
    tmp.rename(INBOX / name)


def main():
    while True:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        if load_last_fired() != today and now.time() >= REMINDER_TIME:
            drop_message(MESSAGE)
            save_last_fired(today)
            print(f"daily_reminder: fired for {today}", file=sys.stderr)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
