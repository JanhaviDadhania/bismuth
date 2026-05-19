"""
Filesystem dropbox watcher.

Watches {BISMUTH_MEMORY}/dropbox/ for new files. When one appears (and has
stopped growing, so we don't grab files mid-write), the watcher moves it to
{BISMUTH_MEMORY}/_dropbox_received/<name> and drops a synthetic message
telling the agent where the file now lives.

This is the non-Telegram input channel: janhavi rsyncs/syncthings/airdrops
a file into the dropbox folder, and the assistant picks it up within a few
seconds.
"""

import os
import sys
import time
import uuid
from pathlib import Path

INBOX = Path(os.environ["SYNTHETIC_INBOX"])
MEMORY = Path(os.environ["BISMUTH_MEMORY"])
DROPBOX = MEMORY / "dropbox"
RECEIVED = MEMORY / "_dropbox_received"

POLL_INTERVAL = 5         # seconds between scans
STABILITY_DELAY = 2       # seconds — wait this long to confirm file isn't mid-write


def drop_message(text: str):
    name = f"fs_dropbox_{uuid.uuid4().hex}.txt"
    tmp = INBOX / (name + ".tmp")
    tmp.write_text(text)
    tmp.rename(INBOX / name)


def process_file(f: Path):
    """Move f into RECEIVED and notify the agent. Skips files that are still
    being written (size changes during STABILITY_DELAY)."""
    try:
        initial_size = f.stat().st_size
    except FileNotFoundError:
        return
    time.sleep(STABILITY_DELAY)
    try:
        if f.stat().st_size != initial_size:
            return  # still being written; try next poll
    except FileNotFoundError:
        return

    target = RECEIVED / f.name
    counter = 0
    while target.exists():
        counter += 1
        target = RECEIVED / f"{f.stem}_{counter}{f.suffix}"

    try:
        f.rename(target)
    except OSError as e:
        print(f"fs_dropbox: rename failed for {f}: {e}", file=sys.stderr)
        return

    drop_message(f"[fs-dropbox: {f.name} saved at {target}]")
    print(f"fs_dropbox: routed {f.name} -> {target}", file=sys.stderr)


def main():
    DROPBOX.mkdir(parents=True, exist_ok=True)
    RECEIVED.mkdir(parents=True, exist_ok=True)
    print(f"fs_dropbox: watching {DROPBOX}, routing to {RECEIVED}",
          file=sys.stderr)
    while True:
        try:
            for f in DROPBOX.iterdir():
                if f.is_file() and not f.name.startswith("."):
                    process_file(f)
        except Exception as e:
            print(f"fs_dropbox: scan error: {e}", file=sys.stderr)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
