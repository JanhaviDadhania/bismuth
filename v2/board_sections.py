"""Board sections for v2 — §4.12.

R1 froze the board's design, so this adds and changes nothing that already
renders: a `Tasks` section in the main space, an `others/` panel with its own
count, and a secondary strip of acks and recently-completed tasks at the foot.

Everything here is read from the trace. The board holds no state of its own,
so it can be regenerated at any time and can never disagree with the record.
"""

from __future__ import annotations

from pathlib import Path

from . import config as cfg
from . import tasks as tasklib


def _card(board, cid: str, title: str, items: list[dict], meta: str):
    card = board.Card(cid=board._cid(cid), kind="todo", title=title,
                      items=items, meta=meta)
    card.tilt = board._tilt(card.cid)
    return card


def build(board, memory: Path) -> list[tuple[str, list]]:
    """Returns board sections: [(SECTION TITLE, [Group, ...]), ...].

    `board` is the tools.board module, passed in so this file never imports
    the renderer at module scope — the board must keep working with v2 absent.

    Returns nothing when `memory` is not the tree v2 is configured for. The
    board can be pointed anywhere with `--memory`, and v2's trace and `others/`
    belong to exactly one tree — rendering one tree's tasks onto another's
    board would be a quiet lie about where her work lives.
    """
    try:
        if Path(memory).resolve() != Path(cfg.MEMORY_DIR).resolve():
            return []
    except OSError:
        return []
    proj = tasklib.fold()
    sections: list[tuple[str, list]] = []

    # ─── main space: Tasks (NEEDS YOU above WORKING) ────────────────────────
    unclear = proj.by_state("unclear")
    working = proj.by_state("working")
    cards = []
    if unclear:
        cards.append(_card(board, "v2:needsyou", f"Needs you ({len(unclear)})",
                           [{"text": f"{t.request} — {t.question or 'waiting on you'}",
                             "done": False, "who": ""} for t in unclear],
                           f"{len(unclear)} waiting on you"))
    if working:
        cards.append(_card(board, "v2:working", f"Working ({len(working)})",
                           [{"text": f"{t.request} — {len(t.open_subagents())} running",
                             "done": False, "who": ""} for t in working],
                           f"{len(working)} in flight"))
    if cards:
        sections.append(("TASKS", [board.Group(
            gid="v2tasks", title="Tasks", kind="now",
            subtitle=f"{len(unclear)} need you · {len(working)} working — "
                     f"bismuth's live list",
            cards=cards)]))

    # ─── others/ — its own panel, its own count (§4.8) ──────────────────────
    parked = sorted(cfg.OTHERS_DIR.glob("*.md")) if cfg.OTHERS_DIR.exists() else []
    if parked:
        items = []
        for f in parked[-20:]:
            body = ""
            try:
                lines = [l.strip() for l in f.read_text().splitlines() if l.strip()]
                body = next((l for l in lines if not l.startswith("#")), f.name)
            except OSError:
                body = f.name
            items.append({"text": body[:140], "done": False, "who": ""})
        sections.append(("OTHERS", [board.Group(
            gid="v2others", title="others/", kind="now",
            subtitle=f"{len(parked)} parked — destination unknown, waiting on you",
            cards=[_card(board, "v2:others", f"Parked ({len(parked)})", items,
                         f"{len(parked)} parked")])]))

    # ─── secondary strip: acks and recently done ───────────────────────────
    strip = []
    acks = proj.acks[-cfg.ACK_TAIL:]
    if acks:
        items = []
        for a in reversed(acks):
            where = ", ".join(Path(d.get("path", "")).name
                              for d in (a.get("destinations") or []) if d.get("path"))
            text = f"{(a.get('transcript') or '')[:90]} → {where or a.get('status')}"
            items.append({"text": text, "done": a.get("status") == "saved", "who": ""})
        strip.append(_card(board, "v2:acks", f"Saved ({len(acks)})", items,
                           "recent notes"))
    done = proj.done_tail[-cfg.ACK_TAIL:]
    if done:
        strip.append(_card(board, "v2:done", f"Finished ({len(done)})",
                           [{"text": d["request"][:120], "done": True, "who": ""}
                            for d in reversed(done)], "recent tasks"))
    if strip:
        sections.append(("RECEIPTS", [board.Group(
            gid="v2receipts", title="Receipts", kind="now",
            subtitle="acks and finished tasks — reassurance, not live work",
            cards=strip)]))

    return sections
