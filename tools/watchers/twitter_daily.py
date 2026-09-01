"""
Twitter daily watcher — janhavi's morning tech/AI feed digest.

Fires once per day at or after FIRE_TIME (08:30 local). Drops a
"[twitter daily] ..." synthetic message; the agent then scrolls
twitter/x via silicon-browser, compiles the cutting-edge tech/AI
happenings, and saves a dated txt under
{BISMUTH_MEMORY}/projects/nostayidiot/twitterdaily/.

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
MEMORY = os.environ.get("BISMUTH_MEMORY", "~/bismuth-memory")
FIRE_TIME = dtime(8, 30)
POLL_INTERVAL = 60  # check every minute

MESSAGE_TEMPLATE = (
    "[twitter daily] scroll twitter (x.com via silicon-browser) for a while, "
    "read the timeline + what's trending in tech/AI, and compile what all "
    "cutting-edge things happened. Save the digest as "
    "{memory}/projects/nostayidiot/twitterdaily/{date}.txt. "
    "The folder's CLAUDE.md has the contract (format, fallbacks, guardrails)."
)


def load_last_fired() -> str:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text()).get("last_fired", "")
        except Exception as e:
            print(f"twitter_daily: state read failed: {e}", file=sys.stderr)
            return ""
    return ""


def save_last_fired(date: str):
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"last_fired": date}))
    tmp.rename(STATE)


def drop_message(text: str):
    name = f"twitter_daily_{uuid.uuid4().hex}.txt"
    tmp = INBOX / (name + ".tmp")
    tmp.write_text(text)
    tmp.rename(INBOX / name)


def main():
    while True:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        if load_last_fired() != today and now.time() >= FIRE_TIME:
            drop_message(MESSAGE_TEMPLATE.format(memory=MEMORY, date=today))
            save_last_fired(today)
            print(f"twitter_daily: fired for {today}", file=sys.stderr)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
