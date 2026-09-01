"""The DESTINATIONS block — §4.6.

The main agent runs with no tools, so it cannot check whether a path exists,
yet the one hard routing guard is that the destination must already exist.
The runtime therefore hands it the real memory tree every turn, including
which folders carry a CLAUDE.md — which is also what lets it satisfy the
§4.9.1 repair (name the context file in the instruction) without guessing.
"""

from __future__ import annotations

from pathlib import Path

from . import config as cfg

SKIP_DIRS = {".git", ".harness", "__pycache__", "node_modules", ".obsidian",
             "trace", ".bismuth", ".venv", "_archive", "_dropbox_received"}
MAX_DEPTH = 4
NAME_THRESHOLD = 8      # list filenames below this, a count and a sample above
SAMPLE = 3


def scan(root: Path | None = None) -> dict:
    """Walk the memory tree once. Returns folders (with their markdown files
    and CLAUDE.md flag), so the block can be rendered compactly."""
    root = root or cfg.MEMORY_DIR
    folders: dict[str, dict] = {}
    if not root.exists():
        return folders

    for path in sorted(root.rglob("*")):
        if not path.is_dir():
            continue
        rel_parts = path.relative_to(root).parts
        if any(p in SKIP_DIRS or p.startswith(".") for p in rel_parts):
            continue
        if len(rel_parts) > MAX_DEPTH:
            continue
        rel = "/".join(rel_parts)
        files = sorted(f.name for f in path.glob("*.md"))
        folders[rel] = {
            "files": files,
            "claude_md": (path / "CLAUDE.md").exists(),
            "abs": str(path),
        }

    root_files = sorted(f.name for f in root.glob("*.md"))
    folders[""] = {"files": root_files,
                   "claude_md": (root / "CLAUDE.md").exists(),
                   "abs": str(root)}
    return folders


def render(folders: dict | None = None, root: Path | None = None) -> str:
    """~3.2k tokens on her current tree, so it is injected once per session and
    re-sent only when the tree changes — not on every turn.

    Filenames are included rather than folder names alone, and that is worth
    the extra ~1.3k: without them the agent guesses `nexttodo.md` against a
    real `next_todo.md`, the worker dutifully creates the wrong file, and her
    notes silently split in two. That is precisely the failure R3 exists to
    prevent."""
    root = root or cfg.MEMORY_DIR
    folders = scan(root) if folders is None else folders
    lines = [f"DESTINATIONS (memory root: {root})",
             "  Route only into a folder listed here, or to others/.",
             "  A file that does not exist yet is fine — say so in the",
             "  instruction, and have the worker create it.",
             "  * = the folder has a CLAUDE.md; name it in the instruction."]
    for rel in sorted(folders, key=lambda r: (r != "", r)):
        info = folders[rel]
        star = " *" if info["claude_md"] else ""
        lines.append(f"  {rel or '(root)'}{star}")
        files = info["files"]
        if not files:
            continue
        if len(files) <= NAME_THRESHOLD:
            lines.append("      " + ", ".join(files))
        else:
            lines.append(f"      [{len(files)} files] " + ", ".join(files[:SAMPLE]) + ", …")
    return "\n".join(lines)


def fingerprint(folders: dict | None = None, root: Path | None = None) -> str:
    """Changes when the tree changes, so the runtime knows to re-send the
    block mid-session (a folder she created since the session started)."""
    import hashlib
    folders = scan(root) if folders is None else folders
    payload = "|".join(
        f"{k}:{len(v['files'])}:{int(v['claude_md'])}" for k, v in sorted(folders.items())
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def resolve(destination: str, root: Path | None = None) -> Path | None:
    """Absolute path for a destination the agent named, or None if it is not
    real. The runtime's own check — the prompt asks the agent to obey the
    DESTINATIONS block, this is what happens when it doesn't (§4.6)."""
    root = root or cfg.MEMORY_DIR
    if not destination:
        return None
    candidate = (root / destination.lstrip("/")).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None                      # escaped the memory tree
    if candidate.exists():
        return candidate
    if candidate.suffix and candidate.parent.exists():
        return candidate                 # new file in an existing folder is fine
    return None
