#!/usr/bin/env python3
"""
Board Tool
Renders the whole memory tree as ONE infinite HTML canvas — the visual surface
that replaces scrolling back through a Telegram thread.

Every project and miniproject becomes a group box on a single pannable,
zoomable white canvas. Inside a group: notes, images, videos, files — each a
card. Long notes and big videos are links, not embedded payloads. Reminders get
their own group, rendered from `reminders.md` as a month-by-month timeline.

Importable:
    from tools.board import build_board
    result = build_board()          # {"success": bool, "out"/"error": str, ...}

CLI:
    python3 tools/board.py                 # writes <memory>/board.html
    python3 tools/board.py --open          # ...and opens it in the browser
    python3 tools/board.py --json          # one JSON object to stdout

No third-party dependencies — stdlib only.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import json
import re
import sys
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from config import MEMORY_DIR as _CFG_MEMORY_DIR
except Exception:  # config.yaml missing / pyyaml absent — --memory still works
    _CFG_MEMORY_DIR = None


# ---------------------------------------------------------------- what to skip

# Vendored and machine-generated trees. Without these the memory tree scans to
# ~90k files (node_modules, site-packages) instead of the ~1.3k that are hers.
IGNORE_DIRS = {
    ".git", ".hg", ".svn",
    "node_modules", "site-packages", "__pycache__", ".ipynb_checkpoints",
    ".venv", "venv", "env", ".env", ".tox",
    "dist", "build", "target", "out", ".next", ".nuxt", ".output",
    ".cache", ".parcel-cache", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".idea", ".vscode", ".claude", ".obsidian",
    "coverage", "htmlcov", ".gradle", ".terraform",
}

IGNORE_EXTS = {
    ".pyc", ".pyo", ".pyd", ".so", ".o", ".a", ".dylib", ".dll", ".class",
    ".map", ".lock", ".whl", ".egg", ".tsbuildinfo", ".log",
}

IGNORE_NAMES = {
    ".DS_Store", ".gitkeep", ".gitignore", ".gitattributes", ".npmrc",
    ".prettierignore", ".prettierrc", ".editorconfig", ".dockerignore",
    "package-lock.json", "yarn.lock", "poetry.lock", "pnpm-lock.yaml",
    "board.html",
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".ogv"}
AUDIO_EXTS = {".m4a", ".mp3", ".ogg", ".wav", ".aac", ".flac"}
NOTE_EXTS = {".md", ".txt", ".markdown", ".rst", ".org"}

# The files that carry a project's identity — pinned to the top of its group.
SPINE_ORDER = ["summary.md", "vision.md", "mood.md", "nexttodo.md", "to_read.md"]

# Inline a video only if it is small; longer ones become links, as instructed.
INLINE_VIDEO_MAX_BYTES = 8 * 1024 * 1024
# Embed a note's full text for the expand overlay only up to this size.
FULL_NOTE_MAX_CHARS = 60_000
PREVIEW_CHARS = 620
# A folder with more eligible files than this collapses to one card that
# lists the file names instead of pinning a card per file.
DEFAULT_MAX_DIR_FILES = 40
# Even a listing has to stop somewhere; the overflow is stated on the card.
FOLDER_LIST_MAX = 60


# ------------------------------------------------------------------- geometry

CARD_W = 250
GAP = 18
GROUP_PAD = 26
GROUP_TITLE_H = 70
GROUP_GAP = 110
SECTION_GAP = 260
SECTION_HEADER_H = 210
# Groups are packed into a landscape board rather than one tall column.
BOARD_ASPECT = 1.8
# No group may tower past this; it grows sideways instead.
MAX_GROUP_H = 2400


@dataclass
class Card:
    cid: str
    kind: str            # spine | note | image | video | audio | file | repo | folder | month
    title: str
    subpath: str = ""    # folder tag shown on the card
    href: str = ""       # url-quoted path, relative to the html file
    preview: str = ""
    meta: str = ""
    full: str | None = None
    items: list = field(default_factory=list)   # for month cards
    w: int = CARD_W
    h: int = 0
    x: int = 0
    y: int = 0
    tilt: float = 0.0


@dataclass
class Group:
    gid: str
    title: str
    kind: str            # project | miniproject | reminders
    subtitle: str = ""
    cards: list = field(default_factory=list)
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0


# --------------------------------------------------------------------- helpers

def _cid(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _tilt(seed: str) -> float:
    """Deterministic micro-rotation so the board reads as pinned paper, not a
    spreadsheet. Deterministic matters: a regenerated board must not reshuffle."""
    n = int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8], 16)
    return round(((n % 240) - 120) / 100.0, 2)   # -1.2deg .. +1.2deg


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def _rel_href(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    return urllib.parse.quote(rel)


def _strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"^\s*[#>]+\s*", "", text, flags=re.M)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*`~]+", "", text)   # not `_` — it eats snake_case names
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _is_repo(d: Path) -> bool:
    return (d / ".git").exists()


def _skip_file(p: Path) -> bool:
    return (
        p.name in IGNORE_NAMES
        or p.suffix.lower() in IGNORE_EXTS
        or p.name.startswith("._")
        or p.name.endswith("~")
    )


# --------------------------------------------------------------------- scanning

def _note_card(path: Path, root: Path, subpath: str) -> Card:
    raw = _read_text(path)
    body = _strip_markdown(raw)
    preview = body[:PREVIEW_CHARS]
    if len(body) > PREVIEW_CHARS:
        preview = preview.rsplit(" ", 1)[0] + " …"
    words = len(body.split())
    return Card(
        cid=_cid(str(path)),
        kind="spine" if path.name in SPINE_ORDER and subpath == "" else "note",
        title=path.stem.replace("_", " "),
        subpath=subpath,
        href=_rel_href(path, root),
        preview=preview,
        meta=f"{words} words" if words else "empty",
        full=raw[:FULL_NOTE_MAX_CHARS] if raw else "",
    )


def _media_card(path: Path, root: Path, subpath: str, size: int) -> Card:
    ext = path.suffix.lower()
    href = _rel_href(path, root)
    base = dict(cid=_cid(str(path)), title=path.name, subpath=subpath,
                href=href, meta=_human_size(size))
    if ext in IMAGE_EXTS:
        return Card(kind="image", **base)
    if ext in VIDEO_EXTS:
        # Long/large video → a link card, never an embedded payload.
        return Card(kind="video" if size <= INLINE_VIDEO_MAX_BYTES else "file", **base)
    if ext in AUDIO_EXTS:
        return Card(kind="audio", **base)
    return Card(kind="file", **base)


def _collect(project_dir: Path, root: Path, max_dir_files: int,
             collapsed: list) -> list:
    """Walk one project folder into cards. Nested git repos and oversized
    folders collapse to a single card instead of exploding into hundreds."""
    cards: list[Card] = []

    def walk(d: Path):
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        files = [p for p in entries if p.is_file() and not _skip_file(p)]
        dirs = [p for p in entries if p.is_dir() and p.name not in IGNORE_DIRS
                and not p.name.startswith(".")]

        subpath = d.relative_to(project_dir).as_posix() if d != project_dir else ""

        if d != project_dir and len(files) > max_dir_files:
            collapsed.append((f"{project_dir.name}/{subpath}", len(files), "large folder"))
            cards.append(Card(
                cid=_cid(str(d)), kind="folder", title=d.name + "/",
                subpath=Path(subpath).parent.as_posix().replace(".", ""),
                href=_rel_href(d, root), meta=f"{len(files)} files",
                items=[{"n": f.name, "h": _rel_href(f, root)} for f in files],
            ))
            return

        for f in files:
            if f.suffix.lower() in NOTE_EXTS:
                cards.append(_note_card(f, root, subpath))
            else:
                try:
                    size = f.stat().st_size
                except OSError:
                    size = 0
                cards.append(_media_card(f, root, subpath, size))

        for sub in dirs:
            if _is_repo(sub):
                collapsed.append((f"{project_dir.name}/{sub.relative_to(project_dir).as_posix()}",
                                  0, "git repo"))
                cards.append(Card(
                    cid=_cid(str(sub)), kind="repo", title=sub.name,
                    subpath=Path(sub.relative_to(project_dir).as_posix()).parent.as_posix().replace(".", ""),
                    href=_rel_href(sub, root), meta="git repo",
                    preview="Code repository — kept whole, not pinned file by file.",
                ))
                continue
            walk(sub)

    walk(project_dir)

    rank = {"spine": 0, "note": 1, "image": 2, "video": 3, "audio": 4,
            "file": 5, "folder": 6, "repo": 7}

    def sort_key(c: Card):
        if c.kind == "spine":
            try:
                spine_i = SPINE_ORDER.index(c.title.replace(" ", "_") + ".md")
            except ValueError:
                spine_i = len(SPINE_ORDER)
            return (0, spine_i, c.title)
        return (rank.get(c.kind, 9), 0, c.subpath + "/" + c.title)

    cards.sort(key=sort_key)
    for c in cards:
        c.tilt = _tilt(c.cid)
    return cards


# -------------------------------------------------------------------- reminders

REMINDER_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*[—–-]\s*(.*)$", re.S)


def _parse_reminder(line: str):
    """`- YYYY-MM-DD — text`, optionally struck through and annotated `(fired)`.
    Returns (fired, date_str, text) or None. The strike markers and the
    annotation are peeled off first — left in, they leak into the card text."""
    line = line.strip()
    if not line.startswith("- "):
        return None
    body = line[1:].strip()

    fired = False
    m = re.match(r"^~~(.*)~~\s*(\(fired\))?\s*$", body, re.S)
    if m:
        fired, body = True, m.group(1).strip()
    elif re.search(r"\(fired\)\s*$", body):
        fired = True
        body = re.sub(r"\(fired\)\s*$", "", body).strip()

    m = REMINDER_DATE_RE.match(body)
    return (fired, m.group(1), m.group(2)) if m else None


def _reminder_group(memory: Path, today: datetime.date) -> Group | None:
    path = memory / "reminders.md"
    if not path.exists():
        return None

    by_month: dict[str, list] = {}
    total = pending = 0
    for line in _read_text(path).splitlines():
        parsed = _parse_reminder(line)
        if not parsed:
            continue
        fired, date_str, raw = parsed
        try:
            date = datetime.date.fromisoformat(date_str)
        except ValueError:
            continue
        text = _strip_markdown(raw).strip()
        total += 1
        if not fired:
            pending += 1
        state = "fired" if fired else ("overdue" if date < today else
                                       ("today" if date == today else "future"))
        by_month.setdefault(date.strftime("%Y-%m"), []).append(
            {"date": date.isoformat(), "day": date.strftime("%d %b"),
             "text": text, "state": state}
        )

    if not total:
        return None

    cards = []
    for month in sorted(by_month):
        items = sorted(by_month[month], key=lambda i: i["date"])
        label = datetime.date.fromisoformat(month + "-01").strftime("%B %Y")
        card = Card(cid=_cid("reminders:" + month), kind="month", title=label,
                    meta=f"{len(items)} reminder{'s' if len(items) != 1 else ''}",
                    items=items)
        card.tilt = _tilt(card.cid)
        cards.append(card)

    return Group(gid="reminders", title="Reminders", kind="reminders",
                 subtitle=f"{pending} pending of {total} — from reminders.md",
                 cards=cards)


# ----------------------------------------------------------------------- layout

def _card_height(c: Card) -> int:
    if c.kind in ("spine", "note"):
        lines = min(9, max(1, -(-len(c.preview) // 34)))
        return 22 + 16 + 24 + lines * 17
    if c.kind == "image":
        return 170 + 22 + 16 + 20
    if c.kind == "video":
        return 150 + 22 + 16 + 20
    if c.kind == "audio":
        return 54 + 22 + 16 + 20
    if c.kind in ("file",):
        return 88
    if c.kind == "folder":
        shown = min(len(c.items), FOLDER_LIST_MAX)
        overflow = 1 if len(c.items) > FOLDER_LIST_MAX else 0
        return 22 + (16 if c.subpath else 0) + 26 + (shown + overflow) * 16
    if c.kind == "repo":
        return 104
    if c.kind == "month":
        return 30 + 18 + 22 * len(c.items) + 22
    if c.kind == "empty":
        return 74
    return 100


def _pack(cards: list, columns: int) -> tuple[int, int]:
    """Masonry: each card goes to the shortest column. Deterministic."""
    heights = [0] * columns
    for c in cards:
        c.h = _card_height(c)
        col = heights.index(min(heights))
        c.x = col * (CARD_W + GAP)
        c.y = heights[col]
        heights[col] += c.h + GAP
    width = columns * (CARD_W + GAP) - GAP
    return width, (max(heights) - GAP if heights and max(heights) else 0)


def _layout_group(g: Group) -> None:
    n = max(1, len(g.cards))
    if g.kind == "reminders":
        columns = min(4, n)
    else:
        # Aim for a roughly square group: card boxes are ~250x180, so the
        # column count that squares off n cards is sqrt(n * 180/250).
        columns = min(8, max(2, round((n * 0.72) ** 0.5)))
    inner_w, inner_h = _pack(g.cards, columns)
    while inner_h > MAX_GROUP_H and columns < 16:
        columns += 1
        inner_w, inner_h = _pack(g.cards, columns)
    for c in g.cards:
        c.x += GROUP_PAD
        c.y += GROUP_PAD + GROUP_TITLE_H
    g.w = inner_w + GROUP_PAD * 2
    g.h = inner_h + GROUP_PAD * 2 + GROUP_TITLE_H


def _layout_section(groups: list, top: int, row_w: int) -> int:
    """Bottom-left fill: each group drops into the highest free slot that fits.
    Row wrapping alone left big vertical holes under the short groups."""
    placed: list[Group] = []
    for g in groups:
        xs = [0] + [q.x + q.w + GROUP_GAP for q in placed]
        best = None
        for x in sorted(set(xs)):
            if x + g.w > row_w and x > 0:
                continue
            y = top
            for q in placed:
                if q.x < x + g.w and x < q.x + q.w:
                    y = max(y, q.y + q.h + GROUP_GAP)
            if best is None or (y, x) < (best[0], best[1]):
                best = (y, x)
        g.y, g.x = best
        placed.append(g)
    return max((g.y + g.h for g in groups), default=top)


def _pack_board(sections: list, row_w: int) -> tuple[list, int, int]:
    """Place every section top to bottom at this row width. Returns the section
    header rules plus the packed bounding box."""
    rules = []
    y = 60
    for label, gs in sections:
        if not gs:
            continue
        rules.append({"label": label, "x": 0, "y": y, "w": row_w, "rule": True})
        y = _layout_section(gs, y + SECTION_HEADER_H, row_w) + SECTION_GAP
    every = [g for _, gs in sections for g in gs]
    width = max([g.x + g.w for g in every] + [1200])
    return rules, width, max(y - SECTION_GAP, 800)


def _best_board(sections: list) -> list:
    """Search row widths for the one that packs closest to a landscape wall.
    Zoom-to-fit on a portrait board wastes most of the screen."""
    every = [g for _, gs in sections for g in gs]
    widest = max(g.w for g in every)
    best = None
    for step in range(0, 40):
        row_w = widest + step * 500
        rules, w, h = _pack_board(sections, row_w)
        score = abs((w / h) - BOARD_ASPECT)
        if best is None or score < best[0]:
            best = (score, row_w)
    rules, width, _ = _pack_board(sections, best[1])
    for r in rules:
        r["w"] = width
    return rules


# ------------------------------------------------------------------------ render

CSS = """
* { box-sizing: border-box; }
html, body { margin:0; height:100%; overflow:hidden;
  font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, sans-serif;
  color:#1b1b1f; background:#fbfbf8; }
#viewport { position:fixed; inset:0; cursor:grab; }
#viewport.panning { cursor:grabbing; }
#canvas { position:absolute; top:0; left:0; transform-origin:0 0;
  background-color:#fffffe;
  background-image:radial-gradient(#dcdcd4 1px, transparent 1px);
  background-size:28px 28px; }

.group { position:absolute; border:1.5px dashed #cfcfc4; border-radius:16px;
  background:rgba(255,255,255,.55); }
.group.miniproject { border-style:dotted; background:rgba(250,250,244,.6); }
.group.reminders { border-color:#c9b79a; background:rgba(255,251,240,.7); }
.group > .g-title { position:absolute; top:14px; left:22px; right:22px;
  font-size:28px; font-weight:680; letter-spacing:-.6px; }
.group > .g-sub { position:absolute; top:46px; left:24px; right:24px;
  font-size:13px; color:#8a8a80; }
.g-count { font-size:15px; font-weight:500; color:#aeaea4; margin-left:10px; }

.section-rule { position:absolute; border-top:5px solid #e0e0d4; }
.section-label { position:absolute; font-size:130px; font-weight:750;
  letter-spacing:-4px; color:#dedecf; line-height:1; }

.card { position:absolute; width:250px; background:#fff; border:1px solid #e6e6de;
  border-radius:10px; padding:10px 11px; box-shadow:0 1px 2px rgba(0,0,0,.05),
  0 6px 16px rgba(0,0,0,.045); overflow:hidden; cursor:pointer;
  transition:box-shadow .12s, opacity .12s; }
.card:hover { box-shadow:0 2px 4px rgba(0,0,0,.07), 0 12px 28px rgba(0,0,0,.09); z-index:5; }
.card.dragging { z-index:50; box-shadow:0 18px 40px rgba(0,0,0,.18); }
.card.dim { opacity:.14; }
.card .t { font-weight:620; font-size:13px; margin:0 0 3px;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.card .tag { font-size:10px; color:#a4a49a; margin-bottom:5px;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.card .p { font-size:11.5px; color:#54545c; white-space:pre-wrap; overflow:hidden; }

.card.spine { background:#fffdf3; border-color:#e8dfbe; }
.card.note::before, .card.spine::before { content:""; position:absolute; top:0; left:0;
  width:3px; height:100%; background:#dfe4ec; }
.card.spine::before { background:#e0c98a; }
.card.image .thumb { width:100%; height:170px; background:#f4f4ef; border-radius:6px;
  display:block; object-fit:contain; }
.card.video video { width:100%; height:150px; background:#000; border-radius:6px; display:block; }
.card.audio audio { width:100%; margin-top:6px; }
.card.file, .card.repo, .card.folder { background:#f9f9ff; border-color:#e0e0ee; }
.card.repo { background:#f5f7f4; border-color:#d9e2d6; }
.card .kind { position:absolute; top:9px; right:10px; font-size:9px;
  text-transform:uppercase; letter-spacing:.6px; color:#b8b8ae; }

.card.folder .flist { display:flex; flex-direction:column; margin-top:2px; }
.card.folder a.fn { font-size:11px; line-height:16px; color:#4a5a7a; text-decoration:none;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.card.folder a.fn:hover { text-decoration:underline; }
.card.folder .fmore { font-size:10.5px; line-height:16px; color:#9a9a90; }
.card.empty { background:#fafaf6; border-style:dashed; border-color:#e0e0d6;
  box-shadow:none; color:#a8a89e; }
.card.month { background:#fffdf6; border-color:#e8dcc0; }
.card.month .row { display:flex; gap:7px; font-size:11px; padding:2px 0;
  align-items:baseline; line-height:1.5; }
.card.month .d { flex:0 0 44px; color:#98988c; font-variant-numeric:tabular-nums; }
.card.month .x { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.card.month .row.fired .x { color:#b5b5ac; text-decoration:line-through; }
.card.month .row.overdue .x { color:#b1442e; font-weight:600; }
.card.month .row.today .x { color:#0a6b3d; font-weight:700; }

#hud { position:fixed; top:14px; left:14px; z-index:100; display:flex; gap:8px;
  align-items:center; background:rgba(255,255,255,.93); border:1px solid #e4e4dc;
  border-radius:12px; padding:8px 10px; box-shadow:0 4px 18px rgba(0,0,0,.07); }
#hud b { font-size:13px; letter-spacing:-.2px; }
#hud button { font:inherit; font-size:11.5px; border:1px solid #e0e0d8; background:#fff;
  border-radius:7px; padding:4px 9px; cursor:pointer; }
#hud button:hover { background:#f5f5ef; }
#search { font:inherit; font-size:12px; border:1px solid #e0e0d8; border-radius:7px;
  padding:4px 8px; width:170px; }
#zoom { font-size:11px; color:#96968c; font-variant-numeric:tabular-nums; min-width:38px; }
#hint { position:fixed; bottom:12px; left:14px; z-index:100; font-size:11px;
  color:#a8a89e; background:rgba(255,255,255,.85); padding:5px 9px; border-radius:8px; }

#overlay { position:fixed; inset:0; z-index:200; background:rgba(28,28,26,.5);
  display:none; align-items:center; justify-content:center; padding:40px; }
#overlay.on { display:flex; }
#sheet { background:#fff; border-radius:14px; max-width:820px; width:100%;
  max-height:100%; display:flex; flex-direction:column;
  box-shadow:0 30px 80px rgba(0,0,0,.35); }
#sheet header { padding:16px 20px 10px; border-bottom:1px solid #eee; display:flex;
  align-items:baseline; gap:12px; }
#sheet h2 { margin:0; font-size:17px; flex:1; }
#sheet a.open { font-size:12px; color:#2c62c4; text-decoration:none; }
#sheet button { border:none; background:none; font-size:22px; cursor:pointer;
  color:#9a9a90; line-height:1; padding:0 2px; }
#body { padding:16px 20px 22px; overflow:auto; white-space:pre-wrap;
  font: 13px/1.65 ui-monospace, SFMono-Regular, Menlo, monospace; color:#26262c; }
"""


def _esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def _card_html(c: Card) -> str:
    style = (f"left:{c.x}px;top:{c.y}px;width:{c.w}px;height:{c.h}px;"
             f"transform:rotate({c.tilt}deg)")
    tag = f'<div class="tag">{_esc(c.subpath)}/</div>' if c.subpath else ""
    kind_badge = ""
    inner = ""

    if c.kind in ("spine", "note"):
        inner = f'<div class="t">{_esc(c.title)}</div>{tag}<div class="p">{_esc(c.preview)}</div>'
    elif c.kind == "image":
        inner = (f'<img class="thumb" src="{c.href}" alt="{_esc(c.title)}" loading="lazy">'
                 f'<div class="t" style="margin-top:6px">{_esc(c.title)}</div>{tag}')
    elif c.kind == "video":
        inner = (f'<video src="{c.href}" preload="metadata" controls></video>'
                 f'<div class="t" style="margin-top:6px">{_esc(c.title)}</div>{tag}')
    elif c.kind == "audio":
        inner = (f'<div class="t">{_esc(c.title)}</div>{tag}'
                 f'<audio src="{c.href}" preload="none" controls></audio>')
        kind_badge = ""
    elif c.kind == "month":
        rows = "".join(
            f'<div class="row {i["state"]}"><span class="d">{_esc(i["day"])}</span>'
            f'<span class="x" title="{_esc(i["text"])}">{_esc(i["text"])}</span></div>'
            for i in c.items
        )
        inner = f'<div class="t">{_esc(c.title)}</div>{rows}'
    elif c.kind == "folder":
        kind_badge = f'<div class="kind">{_esc(c.meta)}</div>'
        rows = "".join(
            f'<a class="fn" href="{i["h"]}" target="_blank">{_esc(i["n"])}</a>'
            for i in c.items[:FOLDER_LIST_MAX]
        )
        if len(c.items) > FOLDER_LIST_MAX:
            rows += (f'<div class="fmore">+{len(c.items) - FOLDER_LIST_MAX} more — '
                     f'open the folder</div>')
        inner = f'<div class="t">{_esc(c.title)}</div>{tag}<div class="flist">{rows}</div>'
    elif c.kind == "empty":
        inner = f'<div class="t">{_esc(c.title)}</div><div class="p">{_esc(c.preview)}</div>'
    else:  # file | repo | folder
        kind_badge = f'<div class="kind">{_esc(c.meta or c.kind)}</div>'
        inner = (f'<div class="t">{_esc(c.title)}</div>{tag}'
                 f'<div class="p">{_esc(c.preview)}</div>')

    if c.kind in ("image", "video", "audio", "month") and c.meta and c.kind != "month":
        kind_badge = ""

    data = f' data-href="{c.href}"' if c.href else ""
    full = ' data-full="1"' if c.full else ""
    names = " ".join(i.get("n", "") for i in c.items) if c.kind == "folder" else ""
    search = _esc(f"{c.title} {c.subpath} {c.preview} {names}".lower())
    return (f'<div class="card {c.kind}" id="c{c.cid}" style="{style}"'
            f'{data}{full} data-s="{search}">{kind_badge}{inner}</div>')


def _group_html(g: Group) -> str:
    count = f'<span class="g-count">{len(g.cards)}</span>' if g.kind != "reminders" else ""
    sub = f'<div class="g-sub">{_esc(g.subtitle)}</div>' if g.subtitle else ""
    cards = "".join(_card_html(c) for c in g.cards)
    tint = ""
    if g.kind != "reminders":
        hue = int(hashlib.sha1(g.title.encode()).hexdigest()[:6], 16) % 360
        tint = (f"background:hsla({hue},48%,96%,.72);"
                f"border-color:hsl({hue},32%,84%);")
    return (f'<div class="group {g.kind}" style="left:{g.x}px;top:{g.y}px;'
            f'width:{g.w}px;height:{g.h}px;{tint}">'
            f'<div class="g-title">{_esc(g.title)}{count}</div>{sub}{cards}</div>')


JS = r"""
const VP = document.getElementById('viewport');
const CV = document.getElementById('canvas');
const ZOOM = document.getElementById('zoom');
const OV = document.getElementById('overlay');
const POS_KEY = 'bismuth-board-positions-v1';
const VIEW_KEY = 'bismuth-board-view-v1';

let scale = 1, tx = 0, ty = 0;
const cards = Array.from(document.querySelectorAll('.card'));

function apply() {
  CV.style.transform = `translate(${tx}px,${ty}px) scale(${scale})`;
  ZOOM.textContent = Math.round(scale * 100) + '%';
}
function saveView() {
  try { localStorage.setItem(VIEW_KEY, JSON.stringify({scale, tx, ty})); } catch (e) {}
}

/* ---- restore hand-placed cards: dragging a card is meant to stick ---- */
function loadPositions() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(POS_KEY) || '{}'); } catch (e) {}
  for (const [id, xy] of Object.entries(saved)) {
    const el = document.getElementById(id);
    if (el) { el.style.left = xy[0] + 'px'; el.style.top = xy[1] + 'px'; }
  }
}
function savePosition(el) {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(POS_KEY) || '{}'); } catch (e) {}
  saved[el.id] = [parseFloat(el.style.left), parseFloat(el.style.top)];
  try { localStorage.setItem(POS_KEY, JSON.stringify(saved)); } catch (e) {}
}

/* ---- pan ---- */
let panning = false, sx = 0, sy = 0;
VP.addEventListener('mousedown', (e) => {
  if (e.target.closest('.card')) return;
  panning = true; sx = e.clientX - tx; sy = e.clientY - ty;
  VP.classList.add('panning');
});
window.addEventListener('mousemove', (e) => {
  if (panning) { tx = e.clientX - sx; ty = e.clientY - sy; apply(); }
  else if (drag) {
    const el = drag.el;
    el.style.left = (drag.ox + (e.clientX - drag.px) / scale) + 'px';
    el.style.top = (drag.oy + (e.clientY - drag.py) / scale) + 'px';
    if (Math.abs(e.clientX - drag.px) + Math.abs(e.clientY - drag.py) > 4) drag.moved = true;
  }
});
window.addEventListener('mouseup', () => {
  if (panning) { panning = false; VP.classList.remove('panning'); saveView(); }
  if (drag) {
    drag.el.classList.remove('dragging');
    if (drag.moved) savePosition(drag.el);
    drag = null;
  }
});

/* ---- zoom at the cursor ---- */
VP.addEventListener('wheel', (e) => {
  e.preventDefault();
  const k = Math.exp(-e.deltaY * 0.0016);
  const next = Math.min(3, Math.max(0.04, scale * k));
  const r = VP.getBoundingClientRect();
  const mx = e.clientX - r.left, my = e.clientY - r.top;
  tx = mx - (mx - tx) * (next / scale);
  ty = my - (my - ty) * (next / scale);
  scale = next; apply(); saveView();
}, {passive: false});

/* ---- drag a card, click to open it ---- */
let drag = null;
cards.forEach((el) => {
  el.addEventListener('mousedown', (e) => {
    if (e.target.closest('video, audio')) return;
    e.stopPropagation();
    drag = {el, moved: false, px: e.clientX, py: e.clientY,
            ox: parseFloat(el.style.left), oy: parseFloat(el.style.top)};
    el.classList.add('dragging');
  });
  el.addEventListener('click', (e) => {
    if (drag && drag.moved) { e.preventDefault(); return; }
    if (e.target.closest('video, audio')) return;
    if (e.target.closest('a')) return;          // a filename link opens itself
    if (el.dataset.full) openSheet(el);
    else if (el.dataset.href) window.open(el.dataset.href, '_blank');
  });
});

/* ---- long notes read in a sheet, not squeezed into a card ---- */
function openSheet(el) {
  const n = NOTES[el.id.slice(1)];
  if (!n) { if (el.dataset.href) window.open(el.dataset.href, '_blank'); return; }
  document.getElementById('sheet-title').textContent = n.t;
  document.getElementById('body').textContent = n.x;
  const a = document.getElementById('sheet-open');
  a.href = el.dataset.href || '#';
  a.style.display = el.dataset.href ? '' : 'none';
  OV.classList.add('on');
}
document.getElementById('sheet-close').onclick = () => OV.classList.remove('on');
OV.addEventListener('click', (e) => { if (e.target === OV) OV.classList.remove('on'); });
window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') OV.classList.remove('on');
  if (e.key === '0') { fit(); }
});

/* ---- search dims what does not match ---- */
document.getElementById('search').addEventListener('input', (e) => {
  const q = e.target.value.trim().toLowerCase();
  cards.forEach((el) => el.classList.toggle('dim', q && !el.dataset.s.includes(q)));
});

/* ---- fit everything on screen ---- */
function fit() {
  const w = CV.scrollWidth, h = CV.scrollHeight;
  const r = VP.getBoundingClientRect();
  scale = Math.min((r.width - 80) / w, (r.height - 80) / h);
  tx = (r.width - w * scale) / 2;
  ty = (r.height - h * scale) / 2;
  apply(); saveView();
}
document.getElementById('fit').onclick = fit;
document.getElementById('reset').onclick = () => {
  if (!confirm('Reset every card back to its generated position?')) return;
  try { localStorage.removeItem(POS_KEY); } catch (e) {}
  location.reload();
};

loadPositions();
let restored = false;
try {
  const v = JSON.parse(localStorage.getItem(VIEW_KEY) || 'null');
  if (v && v.scale) { scale = v.scale; tx = v.tx; ty = v.ty; apply(); restored = true; }
} catch (e) {}
if (!restored) fit();
"""


def _page(groups: list, rules: list, notes: dict, meta: dict) -> str:
    width = max([g.x + g.w for g in groups] + [r["w"] for r in rules] + [1200]) + 220
    height = max([g.y + g.h for g in groups] + [800]) + 220
    body = "".join(_group_html(g) for g in groups)
    for r in rules:
        body += (f'<div class="section-label" style="left:{r["x"]}px;top:{r["y"]}px">'
                 f'{_esc(r["label"])}</div>')
        if r.get("rule"):
            body += (f'<div class="section-rule" style="left:{r["x"]}px;'
                     f'top:{r["y"] + 150}px;width:{r["w"]}px"></div>')

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bismuth Board</title>
<style>{CSS}</style></head>
<body>
<div id="hud">
  <b>Bismuth Board</b>
  <span id="zoom">100%</span>
  <input id="search" type="search" placeholder="filter cards…">
  <button id="fit">fit</button>
  <button id="reset">reset layout</button>
</div>
<div id="hint">drag background to pan · scroll to zoom · drag a card to re-pin it ·
click a note to read it · generated {_esc(meta['generated'])} ·
{meta['cards']} cards across {meta['groups']} groups</div>
<div id="viewport"><div id="canvas" style="width:{width}px;height:{height}px">{body}</div></div>
<div id="overlay"><div id="sheet">
  <header><h2 id="sheet-title"></h2>
  <a class="open" id="sheet-open" target="_blank">open file ↗</a>
  <button id="sheet-close">&times;</button></header>
  <div id="body"></div>
</div></div>
<script>const NOTES = {json.dumps(notes, ensure_ascii=False)};</script>
<script>{JS}</script>
</body></html>
"""


# ------------------------------------------------------------------------- build

def build_board(memory: Path | str | None = None, out: Path | str | None = None,
                max_dir_files: int = DEFAULT_MAX_DIR_FILES) -> dict:
    """Scan the memory tree and write one self-contained infinite-canvas HTML."""
    memory = Path(memory).expanduser().resolve() if memory else _CFG_MEMORY_DIR
    if memory is None:
        return {"success": False, "error": "no memory path — pass --memory or fix config.yaml"}
    memory = Path(memory)
    if not memory.is_dir():
        return {"success": False, "error": f"memory path is not a directory: {memory}"}

    # The html must sit at the memory root so every card's relative href
    # resolves without absolute file:// paths.
    out_path = Path(out).expanduser().resolve() if out else memory / "board.html"
    if out_path.parent.resolve() != memory.resolve():
        return {"success": False,
                "error": f"--out must be inside {memory} or relative hrefs break"}

    today = datetime.date.today()
    collapsed: list = []

    def section(dirname: str, kind: str) -> list[Group]:
        base = memory / dirname
        if not base.is_dir():
            return []
        made = []
        for d in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if not d.is_dir() or d.name in IGNORE_DIRS or d.name.startswith("."):
                continue
            cards = _collect(d, memory, max_dir_files, collapsed)
            if not cards:
                # Keep the group — an empty project should read as empty, not absent.
                cards = [Card(cid=_cid(str(d) + ":empty"), kind="empty",
                              title="nothing pinned yet",
                              preview="This folder has no notes, images or files.")]
            made.append(Group(gid=_cid(str(d)), title=d.name.replace("_", " "),
                              kind=kind, cards=cards))
        return made

    projects = section("projects", "project")
    minis = section("miniprojects", "miniproject")
    reminders = _reminder_group(memory, today)

    sections = [("PROJECTS", projects), ("MINIPROJECTS", minis)]
    if reminders:
        sections.append(("REMINDERS", [reminders]))

    all_groups = [g for _, gs in sections for g in gs]
    if not all_groups:
        return {"success": False, "error": f"nothing to render under {memory}"}
    for g in all_groups:
        _layout_group(g)
    rules = _best_board(sections)
    groups = all_groups

    notes = {c.cid: {"t": c.title, "x": c.full}
             for g in groups for c in g.cards if c.full}
    n_cards = sum(len(g.cards) for g in groups)
    meta = {"generated": today.strftime("%d %b %Y"), "cards": n_cards,
            "groups": len(groups)}

    html_text = _page(groups, rules, notes, meta)
    out_path.write_text(html_text, encoding="utf-8")

    return {
        "success": True,
        "out": str(out_path),
        "bytes": len(html_text.encode("utf-8")),
        "groups": len(groups),
        "projects": len(projects),
        "miniprojects": len(minis),
        "reminders": len(reminders.cards) if reminders else 0,
        "cards": n_cards,
        "collapsed": [{"path": p, "files": n, "why": why} for p, n, why in collapsed],
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Render the memory tree as one infinite HTML canvas")
    ap.add_argument("--memory", help="memory root (default: config.yaml memory_path)")
    ap.add_argument("--out", help="output html (default: <memory>/board.html)")
    ap.add_argument("--max-dir-files", type=int, default=DEFAULT_MAX_DIR_FILES,
                    help=f"collapse a folder above this many files (default {DEFAULT_MAX_DIR_FILES})")
    ap.add_argument("--open", action="store_true", help="open the board in a browser")
    ap.add_argument("--json", action="store_true", help="print one JSON object instead of a report")
    args = ap.parse_args()

    result = build_board(args.memory, args.out, args.max_dir_files)

    if args.json:
        print(json.dumps(result))
    elif not result["success"]:
        print(f"board: {result['error']}", file=sys.stderr)
    else:
        print(f"board → {result['out']}  ({_human_size(result['bytes'])})")
        print(f"  {result['cards']} cards · {result['projects']} projects · "
              f"{result['miniprojects']} miniprojects · {result['reminders']} reminder months")
        # Never hide a cap: say exactly what was collapsed rather than pretending
        # the board shows every last file.
        if result["collapsed"]:
            print(f"  collapsed to a single card ({len(result['collapsed'])}):")
            for c in result["collapsed"]:
                extra = f", {c['files']} files" if c["files"] else ""
                print(f"    {c['path']}  [{c['why']}{extra}]")

    if result["success"] and args.open:
        webbrowser.open(Path(result["out"]).as_uri())
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
