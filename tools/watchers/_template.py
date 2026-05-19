"""
Watcher template — copy to <name>.py to enable.

The leading underscore in the filename tells the supervisor to skip this file.
When you're ready, copy this to (for example) `camera.py` or `mqtt.py` and the
supervisor will pick it up on its next sweep (within 60 seconds).

Contract:
  - Loop forever (or block on your event source).
  - Drop messages by writing to SYNTHETIC_INBOX atomically:
      *.txt.tmp first, then os.rename to *.txt.
  - Persist any state under WATCHER_STATE_DIR (a per-watcher dir provided
    by the harness — already created before the script starts).
  - Log to stderr; it's captured to {HARNESS_DIR}/watcher_<stem>.log.
  - NEVER read or unlink files in SYNTHETIC_INBOX. The harness owns the
    drain side.
  - Exit non-zero only on genuine failure. The supervisor backs off
    exponentially and after 3 consecutive crashes drops a synthetic
    message so the agent learns about the failure.

Environment provided by the supervisor:
  - SYNTHETIC_INBOX     where messages go
  - WATCHER_STATE_DIR   per-watcher state directory
  - BISMUTH_BASE        repo root
  - BISMUTH_MEMORY      memory root
"""

import os
import time
import uuid
from pathlib import Path

INBOX = Path(os.environ["SYNTHETIC_INBOX"])
INTERVAL = 3600  # seconds — how often this example fires


def drop_message(text: str):
    name = f"example_{uuid.uuid4().hex}.txt"
    tmp = INBOX / (name + ".tmp")
    tmp.write_text(text)
    tmp.rename(INBOX / name)


def main():
    while True:
        drop_message(f"[example: heartbeat at {time.strftime('%H:%M')}]")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
