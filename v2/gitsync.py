"""Memory git loop — the runtime owns it, sub-agents never run git.

*Ruled 2026-08-31.* Several workers can run at once; a commit from inside one
races the others and the sync loop. So the sub-agent prompt forbids `git`
outright and this loop is the only writer, which is also the only way to keep
her standing rule — commit and push local work before pulling — since a
single-shot worker cannot.
"""

from __future__ import annotations

import subprocess

from . import config as cfg
from .trace import Trace


def _git(*args: str, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cfg.MEMORY_DIR), *args],
                          capture_output=True, text=True, timeout=timeout)


def sync(trace: Trace) -> bool:
    """Commit local work, push it, then pull. In that order, always — local
    edits are never at risk from an incoming rebase."""
    if not (cfg.MEMORY_DIR / ".git").exists():
        return False
    try:
        status = _git("status", "--porcelain")
        changed = len(status.stdout.strip().splitlines())
        if changed:
            _git("add", "-A")
            commit = _git("commit", "-m", f"bismuth: {changed} change(s)")
            if commit.returncode != 0 and "nothing to commit" not in commit.stdout:
                trace.append("memory_sync", error=commit.stderr[:500] or commit.stdout[:500])
                return False
        push = _git("push")
        if push.returncode != 0:
            trace.append("memory_sync", error=f"push failed: {push.stderr[:400]}",
                         changed=changed)
            return False
        pull = _git("pull", "--rebase")
        if pull.returncode != 0:
            trace.append("memory_sync", error=f"pull failed: {pull.stderr[:400]}",
                         changed=changed)
            return False
        if changed:
            trace.append("memory_sync", changed=changed, pushed=True)
        return True
    except Exception as exc:
        trace.append("memory_sync", error=str(exc))
        return False
