#!/usr/bin/env python3
"""
Race-safe append for shared memory files (tracking.md and friends).

Multiple writers — the active agent plus up to 3 executors — can hit
tracking.md in the same window. Whole-file rewrites race: last writer wins
and silently erases the other's entry. This CLI does the read-modify-write
under an exclusive flock, so concurrent entries can't be lost.

Usage:
    python3 tools/track_append.py <file> "<entry line>"
    python3 tools/track_append.py <file> "<entry line>" --project seldon

With --project, the entry is inserted inside the existing
<project:NAME>...</project:NAME> block (the block is created at end of file
if missing). Without it, the entry is appended at end of file.
"""

import argparse
import fcntl
import os
import sys


def insert_entry(content: str, entry: str, project: str | None = None) -> str:
    entry = entry.rstrip("\n")
    if project:
        open_tag = f"<project:{project}>"
        close_tag = f"</project:{project}>"
        idx = content.find(close_tag)
        if idx != -1:
            before = content[:idx]
            if before and not before.endswith("\n"):
                before += "\n"
            return before + entry + "\n" + content[idx:]
        if content and not content.endswith("\n"):
            content += "\n"
        sep = "\n" if content.strip() else ""
        return content + sep + f"{open_tag}\n{entry}\n{close_tag}\n"
    if content and not content.endswith("\n"):
        content += "\n"
    return content + entry + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Append a line to a shared memory file under an exclusive lock."
    )
    ap.add_argument("file", help="absolute path to the file (e.g. tracking.md)")
    ap.add_argument("entry", help="the line to append")
    ap.add_argument("--project", default=None,
                    help="insert inside the <project:NAME> block instead of at EOF")
    args = ap.parse_args()

    fd = os.open(args.file, os.O_RDWR | os.O_CREAT, 0o644)
    with os.fdopen(fd, "r+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        content = f.read()
        f.seek(0)
        f.truncate()
        f.write(insert_entry(content, args.entry, args.project))
        f.flush()
        os.fsync(f.fileno())
    print(f"appended to {args.file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
