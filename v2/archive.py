"""Audio archive — §4.1. Kept forever, in a separate private repo.

The load-bearing rule: **a note is never blocked, delayed, or failed by the
archive.** Ingest *moves* the staged file into the archive working tree — a
local rename, which cannot fail on the network — and returns. A background
pusher commits and pushes on a timer. If GitHub is down for a day, a day of
audio waits locally and the notes process normally.
"""

from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime
from pathlib import Path

from . import config as cfg
from .trace import Trace


def archive_path(trace_id: str, when: datetime, suffix: str = ".ogg") -> Path:
    stamp = when.strftime("%Y%m%dT%H%M%S%z")
    return cfg.AUDIO_REPO / f"{when:%Y}" / f"{when:%m}" / f"{stamp}__{trace_id}{suffix}"


def archive(staged: Path, trace_id: str, trace: Trace) -> Path | None:
    """Local move into the archive working tree. Off the critical path: any
    failure here is traced and swallowed, never raised at the note."""
    try:
        when = datetime.now().astimezone()
        dest = archive_path(trace_id, when, staged.suffix or ".ogg")
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = staged.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        staged.replace(dest)
        trace.append("audio_archived", trace_id=trace_id, archive_path=str(dest),
                     sha256=digest, bytes=len(data))
        return dest
    except Exception as exc:
        trace.append("audio_archive_failed", trace_id=trace_id, error=str(exc),
                     staged=str(staged))
        return None


def push(trace: Trace) -> bool:
    """Commit and push whatever has accumulated. Retried on the next tick;
    a failure never touches a note."""
    if not (cfg.AUDIO_REPO / ".git").exists():
        return False
    try:
        status = subprocess.run(["git", "-C", str(cfg.AUDIO_REPO), "status", "--porcelain"],
                                capture_output=True, text=True, timeout=60)
        if not status.stdout.strip():
            return True
        files = len(status.stdout.strip().splitlines())
        subprocess.run(["git", "-C", str(cfg.AUDIO_REPO), "add", "-A"],
                       check=True, capture_output=True, timeout=120)
        subprocess.run(["git", "-C", str(cfg.AUDIO_REPO), "commit", "-m",
                        f"audio: {files} note(s)"],
                       check=True, capture_output=True, timeout=120)
        pushed = subprocess.run(["git", "-C", str(cfg.AUDIO_REPO), "push"],
                                capture_output=True, text=True, timeout=300)
        if pushed.returncode != 0:
            trace.append("audio_pushed", error=pushed.stderr[:500], files=files)
            return False
        head = subprocess.run(["git", "-C", str(cfg.AUDIO_REPO), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=60)
        trace.append("audio_pushed", commit=head.stdout.strip(), files=files)
        return True
    except Exception as exc:
        trace.append("audio_pushed", error=str(exc))
        return False
