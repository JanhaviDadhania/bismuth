"""The TOOLS block — Part B. What a worker can reach.

`destinations.py` opens with the reason this file has to exist, and the same
sentence holds with "tool" in place of "path":

    The main agent runs with no tools, so it cannot check whether a path
    exists, yet the one hard routing guard is that the destination must
    already exist.

Today `main_agent.md` names no browser and no robot, so *"scroll twitter for
me"* is answered *"I can't do that"* — while a worker with `Bash` sitting one
intent away could have done it. The agent needs the **index**, so it knows a
capability exists at all. It does not need the manual; the worker reads that.

    ~/bismuth-memory/_tools/*.md     one card per tool

Only the frontmatter is parsed. The body is prose for a worker, so there is no
parser to crash: a malformed card simply does not appear in the index.

Cards are written by a **worker**, never by the runtime — the opposite of
schedules, and the asymmetry is the point. A card needs investigation: run
`--help`, read the README, try a command, write down what actually happened.
A schedule is four structured fields that must be written reliably. Long-form
that benefits from exploration → worker. Short structured data that must not
fail → runtime.
"""

from __future__ import annotations

from pathlib import Path

from . import config as cfg
# Shared with schedules.py on purpose. Both read a markdown card out of a
# reserved `_` folder; two copies of the same reader would drift.
from .schedules import frontmatter
from .trace import Trace


def scan(root: Path | None = None, trace: Trace | None = None) -> dict:
    """Every readable card, by name. A card that will not parse is traced and
    skipped — never fatal, because an unreadable card must not be able to stop
    the agent hearing about the other nineteen tools."""
    root = root or cfg.TOOLS_DIR
    cards: dict[str, dict] = {}
    if not root.exists():
        return cards
    for path in sorted(root.glob("*.md")):
        if path.name == "CLAUDE.md" or path.name.startswith("."):
            continue
        try:
            meta = frontmatter(path.read_text())
        except Exception as exc:
            if trace:
                trace.append("tool_card_unreadable", path=str(path),
                             error=str(exc)[:300])
            continue
        name = str(meta.get("name") or path.stem).strip()
        cards[name] = {
            "name": name,
            "binary": str(meta.get("binary") or "").strip(),
            "summary": str(meta.get("summary") or "").strip(),
            "install": str(meta.get("install") or "").strip(),
            "path": str(path),
        }
    return cards


def render(cards: dict | None = None, root: Path | None = None) -> str:
    """~15 tokens a tool, so twenty tools is 300. It rides the DESTINATIONS
    gate — first turn of a session, and again only when the fingerprint
    changes — so the steady-state cost is zero.

    With no cards it is two lines naming the folder, not nothing. That costs
    ~25 tokens on the gated turns and buys the thing the agent cannot get any
    other way: on the very first *"add silicon-browser as a tool"* there is no
    card to copy a path from, and an agent with no tools would otherwise have to
    guess where cards go. Same reasoning as DESTINATIONS — hand it the real
    path rather than hoping it constructs one.
    """
    root = root or cfg.TOOLS_DIR
    cards = scan(root) if cards is None else cards
    if not cards:
        return (f"TOOLS — none described yet. A worker's Bash still reaches "
                f"anything installed on the machine.\n"
                f"  Cards live in {root}/ — one .md per tool. Have a worker "
                f"investigate and write one when she asks.")
    lines = ["TOOLS — a worker's Bash reaches these. Name the tool and its "
             "card in the instruction.",
             "  The card is the manual; you get the index. A worker reads the "
             "card itself.",
             f"  New cards go in {root}/ — one .md per tool."]
    width = max(len(c["name"]) for c in cards.values())
    for name in sorted(cards):
        card = cards[name]
        summary = card["summary"] or "(no summary in the card)"
        line = f"  {name.ljust(width)}  {summary}"
        if not card["binary"] and card["install"]:
            line += "  [NOT INSTALLED]"
        lines.append(line)
        lines.append(f"  {' ' * width}  card: {card['path']}")
    return "\n".join(lines)


def fingerprint(cards: dict | None = None, root: Path | None = None) -> str:
    """Folded into the DESTINATIONS fingerprint rather than carried as a second
    flag. Simpler, and the cost — re-sending DESTINATIONS' 3.2k on the rare
    tool addition — is negligible against a tool she just asked for being
    invisible until the next session reset."""
    import hashlib
    cards = scan(root) if cards is None else cards
    payload = "|".join(f"{k}:{v['summary']}:{v['binary']}"
                       for k, v in sorted(cards.items()))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
