"""Schedules — recurring work on a clock. Part A of the schedules/tools plan.

A schedule is a **markdown file in `_schedules/`, not a Python file**, and that
is the whole design. v1's watchers were `.py`: adding one meant writing code,
which is why exactly two ever existed. Here the twentieth schedule is
identical to the first — a file appears in a folder, and nothing in `v2/` is
edited to accept it.

    ---
    every: daily              # daily | weekly | N_days
    at: "08:30"
    days: [sun]               # weekly only
    enabled: true
    budget_usd: 4.00
    produces: projects/nostayidiot/twitterdaily/{date}.txt
    min_bytes: 500
    summary: morning tech/AI digest from x.com
    ---
    Scroll x.com and write the digest to {MEMORY}/…/{date}.txt.

Two things happen on every tick, and the second is the one that earns its
keep. `tick()` fires what is due; `check_overdue()` asks whether the last
firing actually produced the file it promised. On 2026-07-16 the v1 digest
burned 38 turns and ~$1.53 on a hung snapshot and produced nothing, silently.
A worker returning `done` is not evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime
from pathlib import Path

from . import config as cfg
from . import state
from .trace import Trace

DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass
class Schedule:
    """One parsed `_schedules/*.md`. `name` is the filename stem — the handle
    she uses on Telegram and the key in `state.json`."""
    name: str
    path: Path
    every: str = "daily"                 # daily | weekly | n_days
    at: dtime = field(default_factory=lambda: dtime(9, 0))
    days: tuple[str, ...] = ()
    n: int = 1                           # n_days only
    enabled: bool = True
    budget_usd: float | None = None
    produces: str = ""
    min_bytes: int = 0
    summary: str = ""

    def cadence(self) -> str:
        """One line, for her and for the board."""
        if self.every == "weekly":
            when = ", ".join(self.days) if self.days else "weekly"
            return f"{when} at {self.at:%H:%M}"
        if self.every == "n_days":
            return f"every {self.n} days at {self.at:%H:%M}"
        return f"daily at {self.at:%H:%M}"


# ─── parsing — never fatal (§ the same rule as tool cards) ───────────────────

def _frontmatter(text: str) -> dict:
    """The `---` block at the top, as a dict. Raises on malformed YAML; every
    caller catches, because a hand-edited schedule must not be able to take the
    background thread down with it."""
    if not text.startswith("---"):
        raise ValueError("no frontmatter block")
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError("unterminated frontmatter block")
    import yaml
    meta = yaml.safe_load(text[3:end]) or {}
    if not isinstance(meta, dict):
        raise ValueError(f"frontmatter is {type(meta).__name__}, not a mapping")
    return meta


def _parse_at(raw) -> dtime:
    """`at: "08:30"`. YAML may have already made it a time, or — unquoted —
    the sexagesimal integer 510. Both are accepted; the string is canonical."""
    if isinstance(raw, dtime):
        return raw
    if isinstance(raw, datetime):
        return raw.time()
    if isinstance(raw, int):                       # unquoted 08:30 -> 8*60+30
        return dtime(raw // 60 % 24, raw % 60)
    m = re.match(r"^\s*(\d{1,2})\s*:\s*(\d{2})", str(raw or ""))
    if not m:
        raise ValueError(f"cannot read at: {raw!r} — use at: \"08:30\"")
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"at: {raw!r} is not a wall-clock time")
    return dtime(hour, minute)


def _parse_every(raw, meta: dict) -> tuple[str, int]:
    """`daily`, `weekly`, or an interval: `3_days` / `3 days`, or the literal
    `n_days` with a separate `n:`."""
    text = str(raw or "daily").strip().lower()
    if text in ("daily", "day"):
        return "daily", 1
    if text in ("weekly", "week"):
        return "weekly", 1
    m = re.match(r"^(\d+)[\s_-]*days?$", text)
    if m:
        return "n_days", max(1, int(m.group(1)))
    if text in ("n_days", "n days"):
        return "n_days", max(1, int(meta.get("n") or 1))
    raise ValueError(f"every: {raw!r} — use daily, weekly, or N_days")


def parse(path: Path) -> Schedule:
    """One file to one Schedule. Raises; callers log and skip."""
    return parse_text(path.stem, path.read_text(), path)


def parse_text(name: str, text: str, path: Path) -> Schedule:
    """The parse, off the disk. `create()` and `update()` run the file they are
    about to write through this first, so a schedule that would not load is
    never committed — the runtime writes schedules precisely because they must
    not fail."""
    meta = _frontmatter(text)
    every, n = _parse_every(meta.get("every"), meta)
    days_raw = meta.get("days") or []
    if isinstance(days_raw, str):
        days_raw = re.split(r"[,\s]+", days_raw)
    days = tuple(str(d).strip().lower()[:3] for d in days_raw if str(d).strip())
    for d in days:
        if d not in DAY_NAMES:
            raise ValueError(f"days: {d!r} is not a weekday")
    budget = meta.get("budget_usd")
    return Schedule(
        name=name,
        path=path,
        every=every,
        at=_parse_at(meta.get("at", "09:00")),
        days=days,
        n=n,
        enabled=bool(meta.get("enabled", True)),
        budget_usd=float(budget) if budget is not None else None,
        produces=str(meta.get("produces") or "").strip(),
        min_bytes=int(meta.get("min_bytes") or 0),
        summary=str(meta.get("summary") or "").strip(),
    )


def load_all(trace: Trace | None = None) -> list[Schedule]:
    """Every readable schedule. An unreadable one is traced and skipped — it
    can never stop the others firing."""
    out: list[Schedule] = []
    if not cfg.SCHEDULES_DIR.exists():
        return out
    for path in sorted(cfg.SCHEDULES_DIR.glob("*.md")):
        if path.name == "CLAUDE.md" or path.name.startswith("."):
            continue
        try:
            out.append(parse(path))
        except Exception as exc:
            if trace:
                trace.append("schedule_parse_failed", path=str(path),
                             error=str(exc)[:300])
    return out


def get(name: str, trace: Trace | None = None) -> Schedule | None:
    return next((s for s in load_all(trace) if s.name == name), None)


# ─── writing one ────────────────────────────────────────────────────────────
# Schedules are written by the **runtime**, tool cards by a **worker**, and the
# split is not arbitrary. A card needs investigation — run `--help`, read the
# README, write down what actually happened — which is long-form work that
# benefits from exploration. A schedule is a handful of structured fields that
# must be written reliably. Long-form that benefits from exploration → worker.
# Short structured data that must not fail → runtime.

FIELD_ORDER = ("every", "at", "days", "enabled", "budget_usd", "produces",
               "min_bytes", "summary")


def _yv(value) -> str:
    """One frontmatter value, quoted by yaml so a summary containing a colon
    cannot break the file it is written into."""
    import yaml
    return yaml.safe_dump(value, default_flow_style=True,
                          allow_unicode=True).strip().removesuffix("...").strip()


def render_file(fields: dict, body: str) -> str:
    lines = ["---"]
    for key in FIELD_ORDER:
        if key not in fields or fields[key] is None:
            continue
        value = fields[key]
        if key == "at":
            lines.append(f'at: "{value}"')          # never a sexagesimal int
        elif key == "days" and not value:
            continue
        else:
            lines.append(f"{key}: {_yv(value)}")
    lines += ["---", "", body.strip(), ""]
    return "\n".join(lines)


def slug(name: str) -> str:
    """The filename stem, and her handle for it. Kept strict so a schedule name
    can never become a path."""
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")
    return s[:60]


def write(name: str, fields: dict, body: str, *, must_exist: bool) -> Schedule:
    """Render, parse the render, and only then commit. Raises on anything that
    would not load, or on a name that is not a plain slug."""
    stem = slug(name)
    if not stem:
        raise ValueError(f"{name!r} is not a usable schedule name")
    path = cfg.SCHEDULES_DIR / f"{stem}.md"
    if must_exist and not path.exists():
        known = ", ".join(s.name for s in load_all()) or "(none)"
        raise ValueError(f"no schedule named {stem!r}; known: {known}")
    text = render_file(fields, body)
    sched = parse_text(stem, text, path)            # validate before writing
    cfg.SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return sched


def merge(existing: Schedule, raw_text: str, fields: dict,
          body: str | None) -> tuple[dict, str]:
    """An update changes only what she named. Everything unmentioned — the
    body especially — is carried through unchanged, so `pause the digest` can
    never quietly discard the contract underneath it."""
    current = {
        "every": (f"{existing.n}_days" if existing.every == "n_days"
                  else existing.every),
        "at": f"{existing.at:%H:%M}",
        "days": list(existing.days),
        "enabled": existing.enabled,
        "budget_usd": existing.budget_usd,
        "produces": existing.produces or None,
        "min_bytes": existing.min_bytes or None,
        "summary": existing.summary or None,
    }
    current.update({k: v for k, v in fields.items() if v is not None})
    kept = raw_text.split("\n---", 1)[1].split("\n", 1)[1] if "\n---" in raw_text else ""
    return current, (body if body is not None else kept)


# ─── path expansion ─────────────────────────────────────────────────────────

def expand(template: str, when: date) -> str:
    """`{date}` and `{MEMORY}`, the two placeholders a schedule may use."""
    return (template
            .replace("{date}", when.isoformat())
            .replace("{MEMORY}", str(cfg.MEMORY_DIR)))


def produces_path(sched: Schedule, when: date) -> Path | None:
    """Absolute path of the artifact this schedule promises, or None if it
    promises nothing. Relative paths are relative to the memory root."""
    if not sched.produces:
        return None
    expanded = expand(sched.produces, when)
    p = Path(expanded).expanduser()
    return p if p.is_absolute() else cfg.MEMORY_DIR / p


# ─── is it due? ─────────────────────────────────────────────────────────────

def is_due(sched: Schedule, entry: dict | None, now: datetime) -> bool:
    """**Date-guard, not interval.** Due when it has not already fired today
    *and* the wall clock has passed `at`. Laptop shut at 08:30 and opened at
    14:00 fires at 14:00 — late beats never for a digest.

    Naive local `datetime.now()`, deliberately: "08:30" means wall clock.
    """
    if not sched.enabled:
        return False
    today = now.date()
    entry = entry or {}
    last = entry.get("last_fired")
    if last == today.isoformat():
        return False
    if now.time() < sched.at:
        return False

    if sched.every == "weekly":
        if sched.days:
            return DAY_NAMES[today.weekday()] in sched.days
        return _days_since(last, today) >= 7
    if sched.every == "n_days":
        return _days_since(last, today) >= sched.n
    return True                                    # daily


def _days_since(last: str | None, today: date) -> int:
    """Never fired counts as infinitely long ago, so a new schedule fires on
    its first eligible tick rather than waiting out a full interval."""
    if not last:
        return 10_000
    try:
        return (today - date.fromisoformat(last)).days
    except ValueError:
        return 10_000


# ─── the firing turn ────────────────────────────────────────────────────────

def system_text(sched: Schedule, when: date) -> str:
    """The SYSTEM block carries a **pointer, not the body**.

    Inlining the body would mean the main agent paraphrases it into a worker
    instruction, and that retyping hop is exactly where accumulated contract
    detail — the hashtag scheme, the honesty rule, the 2026-07-16 hang note —
    quietly disappears. A path gives the worker the authoritative text with
    zero paraphrase, and is the idiom `claude_md` already established.

    The one-line `summary` stays because the main agent still has decisions:
    spawn or merely reply, what budget, which task to attach it to, or skip
    because she paused it last night. `date`, `memory root` and the expanded
    `produces` are here so the instruction can carry real paths — the file's
    own `{date}` / `{MEMORY}` are not expanded on disk.
    """
    lines = ["schedule fired",
             f"  name: {sched.name}",
             f"  file: {sched.path}",
             f"  summary: {sched.summary or '(none given)'}",
             f"  cadence: {sched.cadence()}",
             f"  date: {when.isoformat()}",
             f"  memory root: {cfg.MEMORY_DIR}"]
    target = produces_path(sched, when)
    if target:
        lines.append(f"  produces: {target}")
        if sched.min_bytes:
            lines.append(f"  min_bytes: {sched.min_bytes} — the runtime checks "
                         f"this {cfg.SCHEDULE_OVERDUE_AFTER // 3600}h after "
                         f"firing and tells you if it is missing")
    if sched.budget_usd:
        lines.append(f"  budget_usd: {sched.budget_usd}")
    lines.append("  The file is the contract. Have a worker read it and do what "
                 "it says; do not paraphrase it.")
    return "\n".join(lines)


def turn_item(sched: Schedule, when: date) -> dict:
    return {"kind": "system",
            "trace_id": f"sched_{sched.name}_{when.isoformat()}",
            "schedule": sched.name,
            "text": system_text(sched, when)}


def tick(trace: Trace, now: datetime | None = None) -> list[str]:
    """Fire everything due. Returns the names fired, so the caller knows
    whether to wake the main loop.

    **The enqueue and the mark happen in one `state.mutate()` block.** Split
    apart there is a crash window either way — mark-then-enqueue loses a run
    silently, enqueue-then-mark duplicates it. Both live in `state.json`, so
    one locked read-modify-write closes it entirely. This is why `last_fired`
    is runtime state and not frontmatter the runtime rewrites every morning.

    Schedules **do not preempt**: one queue, one turn at a time. If she is
    mid-conversation at 08:30, the schedule waits its turn. "08:30" means "the
    next free slot after 08:30."
    """
    now = now or datetime.now()
    scheds = load_all(trace)                    # parse outside the lock
    if not scheds:
        return []

    fired: list[tuple[Schedule, dict]] = []
    with state.mutate() as s:
        book = s.setdefault("schedules", {})
        for sched in scheds:
            if not is_due(sched, book.get(sched.name), now):
                continue
            item = state.prepare_turn(turn_item(sched, now.date()))
            s["turn_queue"].append(item)
            book[sched.name] = {**(book.get(sched.name) or {}),
                                "last_fired": now.date().isoformat(),
                                "last_fired_at": now.timestamp(),
                                "overdue_flagged": None}
            fired.append((sched, item))

    for sched, item in fired:                   # trace outside the state lock
        target = produces_path(sched, now.date())
        trace.append("schedule_fired", trace_id=item["trace_id"],
                     schedule=sched.name, file=str(sched.path),
                     cadence=sched.cadence(), at=f"{sched.at:%H:%M}",
                     fired_at=now.isoformat(timespec="seconds"),
                     summary=sched.summary,
                     produces=str(target) if target else None,
                     min_bytes=sched.min_bytes or None,
                     item_id=item["item_id"])
    return [s.name for s, _ in fired]


# ─── did it actually produce anything? ──────────────────────────────────────

def check_overdue(trace: Trace, now: datetime | None = None) -> list[str]:
    """A worker returning `done` does not mean the artifact is good.

    For any schedule with `produces:`, if it fired more than
    `cfg.SCHEDULE_OVERDUE_AFTER` ago and the expanded path is missing or
    smaller than `min_bytes`, enqueue a SYSTEM turn saying so.

    Checking here rather than when reaping the worker is deliberate.
    Per-worker checking needs the schedule name threaded through
    `SpawnRequest` and `route_ctx`, and it still misses the worst failure — the
    main agent deciding not to spawn anything at all, which nothing would ever
    notice. The next-tick check catches every path: worker failed, worker lied,
    agent skipped, worker never spawned.

    Debounced on `overdue_flagged`, so a run that never produces its file
    complains **once**, not once a minute until midnight.
    """
    now = now or datetime.now()
    book = state.read().get("schedules") or {}
    flagged: list[tuple[str, dict]] = []

    for sched in load_all(trace):
        entry = book.get(sched.name) or {}
        last = entry.get("last_fired")
        if not sched.produces or not last:
            continue
        if entry.get("overdue_flagged") == last:
            continue
        fired_at = entry.get("last_fired_at")
        if not fired_at or (now.timestamp() - float(fired_at)) < cfg.SCHEDULE_OVERDUE_AFTER:
            continue
        try:
            fire_date = date.fromisoformat(last)
        except ValueError:
            continue
        target = produces_path(sched, fire_date)
        if target is None:
            continue
        size = target.stat().st_size if target.exists() else -1
        if size >= sched.min_bytes and size >= 0:
            continue
        flagged.append((sched.name, {
            "schedule": sched.name, "path": str(target),
            "bytes": size, "min_bytes": sched.min_bytes,
            "fired": last, "summary": sched.summary,
            "missing": size < 0, "file": str(sched.path),
        }))

    if not flagged:
        return []

    items: list[tuple[dict, dict]] = []
    with state.mutate() as s:
        book = s.setdefault("schedules", {})
        for name, detail in flagged:
            entry = book.setdefault(name, {})
            if entry.get("overdue_flagged") == entry.get("last_fired"):
                continue                       # someone else got there first
            item = state.prepare_turn({
                "kind": "system",
                "trace_id": f"overdue_{name}_{detail['fired']}",
                "schedule": name,
                "text": _overdue_text(detail),
            })
            s["turn_queue"].append(item)
            entry["overdue_flagged"] = entry.get("last_fired")
            items.append((detail, item))

    for detail, item in items:
        trace.append("schedule_overdue", trace_id=item["trace_id"], **detail)
    return [d["schedule"] for d, _ in items]


def _overdue_text(d: dict) -> str:
    what = ("it does not exist" if d["missing"]
            else f"it is {d['bytes']} bytes, under the {d['min_bytes']} it promised")
    return "\n".join([
        "a schedule fired but produced nothing usable",
        f"  name: {d['schedule']}",
        f"  file: {d['file']}",
        f"  fired: {d['fired']}",
        f"  expected: {d['path']}",
        f"  found: {what}",
        "  Nobody has told her. Decide: retry it now with a worker, or tell "
        "her it failed and why. Do not silently drop it.",
    ])


# ─── one schedule, on demand — `python3 -m v2 fire <name>` ───────────────────

def fire_now(name: str, trace: Trace, *, force: bool = True,
             now: datetime | None = None) -> dict | None:
    """Enqueue one schedule's turn regardless of the clock. This is the only
    way to test a SYSTEM turn — `feed` covers notes, and nothing else does —
    so it is part of the build, not a convenience.

    `force=False` respects the date-guard, which is what makes it usable as a
    catch-up rather than a duplicate.
    """
    now = now or datetime.now()
    sched = get(name, trace)
    if sched is None:
        return None
    with state.mutate() as s:
        book = s.setdefault("schedules", {})
        if not force and not is_due(sched, book.get(name), now):
            return None
        item = state.prepare_turn(turn_item(sched, now.date()))
        s["turn_queue"].append(item)
        book[name] = {**(book.get(name) or {}),
                      "last_fired": now.date().isoformat(),
                      "last_fired_at": now.timestamp(),
                      "overdue_flagged": None}
    target = produces_path(sched, now.date())
    trace.append("schedule_fired", trace_id=item["trace_id"],
                 schedule=sched.name, file=str(sched.path),
                 cadence=sched.cadence(), at=f"{sched.at:%H:%M}",
                 fired_at=now.isoformat(timespec="seconds"),
                 summary=sched.summary, manual=True,
                 produces=str(target) if target else None,
                 min_bytes=sched.min_bytes or None, item_id=item["item_id"])
    return item


# ─── for `status` and the board ──────────────────────────────────────────────

def render(trace: Trace | None = None) -> str:
    scheds = load_all(trace)
    book = state.read().get("schedules") or {}
    if not scheds:
        return f"SCHEDULES (0) — none in {cfg.SCHEDULES_DIR}"
    lines = [f"SCHEDULES ({len(scheds)}) — {cfg.SCHEDULES_DIR}"]
    for s in scheds:
        entry = book.get(s.name) or {}
        last = entry.get("last_fired") or "never"
        flag = "" if s.enabled else "  [paused]"
        lines.append(f"  {s.name}: {s.cadence()} · last {last}{flag}")
        if s.summary:
            lines.append(f"      {s.summary}")
        if s.produces:
            lines.append(f"      -> {s.produces} (min {s.min_bytes}b)")
    return "\n".join(lines)
