"""Schedules and the tool catalog — the paths that must not break quietly.

Run: python3 -m pytest tests/test_v2_schedules.py -q
Everything runs against a throwaway tree via the `v2` fixture in conftest.py;
nothing touches her real memory, and no test spends money on `claude -p`.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, time as dtime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DAILY = '''---
every: daily
at: "08:30"
enabled: true
budget_usd: 4.00
produces: projects/the_mirror/digest/{date}.txt
min_bytes: 500
summary: morning digest
---
Write the digest to {MEMORY}/projects/the_mirror/digest/{date}.txt.
'''


def write(v2, name, text):
    v2.config.SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
    p = v2.config.SCHEDULES_DIR / f"{name}.md"
    p.write_text(text)
    return p


def at(stamp):
    return datetime.fromisoformat(stamp)


# ─── reserved folders ───────────────────────────────────────────────────────

def test_underscore_folders_are_invisible_to_destinations(v2):
    """If `_schedules/` were routable the agent could file a grocery list into
    it, and `tick()` would then try to parse the grocery list as a schedule."""
    for name in ("_schedules", "_tools", "_archive", "_anything_future"):
        (v2.config.MEMORY_DIR / name).mkdir(exist_ok=True)
    folders = v2.destinations.scan()
    assert "projects/the_mirror" in folders
    for name in ("_schedules", "_tools", "_archive", "_anything_future"):
        assert name not in folders


def test_resolve_rejects_reserved_paths_too(v2):
    """Hiding a folder from the block guards the model. `resolve()` is the
    runtime's guard, and it is the one that actually holds."""
    v2.config.TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    assert v2.destinations.resolve("_tools/silicon-browser.md") is None
    assert v2.destinations.resolve("_schedules/twitter-daily.md") is None
    assert v2.destinations.resolve("projects/the_mirror") is not None
    assert v2.destinations.resolve("projects/the_mirror/new.md") is not None


# ─── parsing — never fatal ──────────────────────────────────────────────────

def test_parses_the_documented_shape(v2):
    write(v2, "digest", DAILY)
    s = v2.schedules.get("digest")
    assert s.at == dtime(8, 30) and s.every == "daily"
    assert s.budget_usd == 4.0 and s.min_bytes == 500
    assert s.cadence() == "daily at 08:30"


def test_weekly_and_interval_cadences(v2):
    write(v2, "review", '---\nevery: weekly\nat: "19:00"\ndays: [sun, wed]\n---\nx\n')
    write(v2, "thrice", '---\nevery: 3_days\nat: 6:15\n---\nx\n')
    assert v2.schedules.get("review").days == ("sun", "wed")
    assert v2.schedules.get("thrice").at == dtime(6, 15)   # unquoted sexagesimal
    assert v2.schedules.get("thrice").n == 3


@pytest.mark.parametrize("body", [
    '---\nevery: fortnightly\nat: "07:00"\n---\nx\n',        # no such cadence
    '---\nevery: daily\nat: "nope"\n---\nx\n',               # not a time
    '---\nevery: daily\nat: "07:00"\ndays: [funday]\n---\nx\n',
    '---\nevery: daily\nat: "07:00"\n  bad: [yaml\n---\nx\n',
    'no frontmatter at all\n',
])
def test_a_broken_schedule_is_skipped_not_fatal(v2, body):
    """`_background` has one thread. A hand-edited file that throws in parse()
    must not be able to stop the other schedules — or audio, git sync and the
    board — from running."""
    write(v2, "good", DAILY)
    write(v2, "broken", body)
    names = [s.name for s in v2.schedules.load_all(v2.trace.Trace())]
    assert names == ["good"]


# ─── the date-guard ─────────────────────────────────────────────────────────

def test_fires_after_at_never_before(v2):
    write(v2, "digest", DAILY)
    s = v2.schedules.get("digest")
    assert not v2.schedules.is_due(s, None, at("2026-09-01T08:29"))
    assert v2.schedules.is_due(s, None, at("2026-09-01T08:31"))


def test_late_beats_never(v2):
    """Laptop shut at 08:30 and opened at 14:00 fires at 14:00."""
    write(v2, "digest", DAILY)
    s = v2.schedules.get("digest")
    assert v2.schedules.is_due(s, {"last_fired": "2026-08-31"}, at("2026-09-01T14:00"))


def test_never_twice_in_one_day(v2):
    write(v2, "digest", DAILY)
    s = v2.schedules.get("digest")
    assert not v2.schedules.is_due(s, {"last_fired": "2026-09-01"},
                                   at("2026-09-01T23:59"))


def test_paused_never_fires(v2):
    write(v2, "digest", DAILY.replace("enabled: true", "enabled: false"))
    assert not v2.schedules.is_due(v2.schedules.get("digest"), None,
                                   at("2026-09-01T23:00"))


def test_interval_and_weekday_gates(v2):
    write(v2, "thrice", '---\nevery: 3_days\nat: "06:00"\n---\nx\n')
    write(v2, "review", '---\nevery: weekly\nat: "19:00"\ndays: [wed]\n---\nx\n')
    thrice, review = v2.schedules.get("thrice"), v2.schedules.get("review")
    assert not v2.schedules.is_due(thrice, {"last_fired": "2026-08-30"}, at("2026-09-01T07:00"))
    assert v2.schedules.is_due(thrice, {"last_fired": "2026-08-29"}, at("2026-09-01T07:00"))
    assert v2.schedules.is_due(thrice, None, at("2026-09-01T07:00"))   # never fired
    assert not v2.schedules.is_due(review, None, at("2026-09-01T20:00"))  # a tuesday
    assert v2.schedules.is_due(review, None, at("2026-09-02T20:00"))      # a wednesday


def test_a_corrupt_last_fired_reads_as_never(v2):
    write(v2, "digest", DAILY)
    assert v2.schedules.is_due(v2.schedules.get("digest"),
                               {"last_fired": "not-a-date"}, at("2026-09-01T09:00"))


# ─── tick: the enqueue and the mark are one write ───────────────────────────

def test_tick_enqueues_and_marks_atomically(v2):
    """Sequenced separately there is a crash window either way:
    mark-then-enqueue loses a run silently, enqueue-then-mark duplicates it."""
    write(v2, "digest", DAILY)
    assert v2.schedules.tick(v2.trace.Trace(), now=at("2026-09-01T09:00")) == ["digest"]
    s = v2.state.read()
    assert len(s["turn_queue"]) == 1
    assert s["turn_queue"][0]["kind"] == "system"
    assert s["schedules"]["digest"]["last_fired"] == "2026-09-01"
    # and the guard holds on the very next tick
    assert v2.schedules.tick(v2.trace.Trace(), now=at("2026-09-01T09:01")) == []
    assert len(v2.state.read()["turn_queue"]) == 1


def test_the_firing_turn_carries_a_pointer_not_the_body(v2):
    """Inlining the body means the agent paraphrases the contract into a worker
    instruction, and that retyping hop is where accumulated detail dies."""
    path = write(v2, "digest", DAILY)
    v2.schedules.tick(v2.trace.Trace(), now=at("2026-09-01T09:00"))
    text = v2.state.read()["turn_queue"][0]["text"]
    assert str(path) in text                       # the pointer
    assert "morning digest" in text                # the summary it decides on
    assert str(v2.config.MEMORY_DIR) in text       # so {MEMORY} can be substituted
    assert "2026-09-01" in text                    # so {date} can be substituted
    assert "projects/the_mirror/digest/2026-09-01.txt" in text   # expanded produces
    assert "Write the digest to" not in text       # NOT the body


# ─── produces: verification, and the debounce ───────────────────────────────

def _fire_then(v2, when, artifact=None):
    v2.schedules.tick(v2.trace.Trace(), now=at(when))
    with v2.state.mutate() as s:
        s["turn_queue"] = []
        s["schedules"]["digest"]["last_fired_at"] = at(when).timestamp()
    if artifact is not None:
        p = v2.config.MEMORY_DIR / "projects/the_mirror/digest" / f"{when[:10]}.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(artifact)


def test_a_missing_artifact_is_reported(v2):
    """A worker returning `done` is not evidence. On 2026-07-16 the v1 digest
    burned 38 turns and ~$1.53 on a hung snapshot and produced nothing."""
    write(v2, "digest", DAILY)
    _fire_then(v2, "2026-09-01T08:31")
    assert v2.schedules.check_overdue(v2.trace.Trace(),
                                      now=at("2026-09-01T12:00")) == ["digest"]
    text = v2.state.read()["turn_queue"][0]["text"]
    assert "does not exist" in text and "Nobody has told her" in text


def test_a_short_artifact_is_a_failure_too(v2):
    write(v2, "digest", DAILY)
    _fire_then(v2, "2026-09-01T08:31", artifact="nothing to report\n")
    assert v2.schedules.check_overdue(v2.trace.Trace(),
                                      now=at("2026-09-01T12:00")) == ["digest"]
    assert "18 bytes" in v2.state.read()["turn_queue"][0]["text"]


def test_a_real_artifact_is_silence(v2):
    write(v2, "digest", DAILY)
    _fire_then(v2, "2026-09-01T08:31", artifact="x" * 600)
    assert v2.schedules.check_overdue(v2.trace.Trace(), now=at("2026-09-01T12:00")) == []


def test_the_two_hour_window_holds(v2):
    write(v2, "digest", DAILY)
    _fire_then(v2, "2026-09-01T08:31")
    assert v2.schedules.check_overdue(v2.trace.Trace(), now=at("2026-09-01T09:30")) == []


def test_the_complaint_is_debounced(v2):
    """Undebounced this is one main-agent turn a minute from 10:30 to midnight
    — about 810 — for a single missed run."""
    write(v2, "digest", DAILY)
    _fire_then(v2, "2026-09-01T08:31")
    assert v2.schedules.check_overdue(v2.trace.Trace(), now=at("2026-09-01T12:00")) == ["digest"]
    with v2.state.mutate() as s:
        s["turn_queue"] = []
    for minute in range(20):
        v2.schedules.check_overdue(v2.trace.Trace(), now=at(f"2026-09-01T12:{minute:02d}"))
    assert v2.state.read()["turn_queue"] == []


def test_a_new_firing_re_arms_the_check(v2):
    write(v2, "digest", DAILY)
    _fire_then(v2, "2026-09-01T08:31")
    v2.schedules.check_overdue(v2.trace.Trace(), now=at("2026-09-01T12:00"))
    _fire_then(v2, "2026-09-02T08:31")
    assert v2.state.read()["schedules"]["digest"]["overdue_flagged"] is None
    assert v2.schedules.check_overdue(v2.trace.Trace(), now=at("2026-09-02T12:00")) == ["digest"]
    # and it checks day two's path, not day one's
    assert "2026-09-02.txt" in v2.state.read()["turn_queue"][0]["text"]


def test_no_produces_is_never_checked(v2):
    write(v2, "chat", '---\nevery: daily\nat: "08:00"\nsummary: say hi\n---\nSay hi.\n')
    v2.schedules.tick(v2.trace.Trace(), now=at("2026-09-01T09:00"))
    with v2.state.mutate() as s:
        s["turn_queue"] = []
        s["schedules"]["chat"]["last_fired_at"] = 0.0
    assert v2.schedules.check_overdue(v2.trace.Trace()) == []


# ─── creating one by talking ────────────────────────────────────────────────

def run_intents(v2, *ints, sent=None):
    ex = v2.intents.Executor(v2.tasks.fold([]), v2.trace.Trace(),
                             sent.append if sent is not None else (lambda t: None))
    return ex.run(list(ints), {"trace_id": "t1", "text": "she said something"})


def test_schedule_create_writes_a_file_that_parses(v2):
    sent = []
    ex = run_intents(v2, {
        "type": "schedule_create", "name": "Twitter Daily!!", "every": "daily",
        "at": "08:30", "budget_usd": 4.0, "min_bytes": 500,
        "produces": "projects/the_mirror/digest/{date}.txt",
        "summary": "morning digest from x.com: the good bits",
        "body": "Scroll x.com and write {MEMORY}/…/{date}.txt.",
    }, sent=sent)
    assert ex.problems == []
    s = v2.schedules.get("twitter-daily")           # slugified from her words
    assert s is not None and s.cadence() == "daily at 08:30"
    assert s.summary.endswith("the good bits")      # a colon did not break the file
    assert 'at: "08:30"' in s.path.read_text()      # never a sexagesimal int
    assert "{MEMORY}" in s.path.read_text()         # left unexpanded on disk


def test_she_is_always_told_the_cadence_and_the_path(v2):
    """A schedule acts repeatedly while she is asleep. The prompt asks for the
    reply; this is what happens when the agent forgets."""
    sent = []
    run_intents(v2, {"type": "schedule_create", "name": "digest", "every": "daily",
                     "at": "08:30", "summary": "x", "body": "do the thing"}, sent=sent)
    assert len(sent) == 1
    assert "daily at 08:30" in sent[0]
    assert str(v2.config.SCHEDULES_DIR / "digest.md") in sent[0]


def test_an_explicit_reply_is_not_doubled(v2):
    sent = []
    run_intents(v2,
                {"type": "schedule_create", "name": "digest", "every": "daily",
                 "at": "08:30", "summary": "x", "body": "do the thing"},
                {"type": "reply", "text": "Set that up — 08:30 daily."}, sent=sent)
    assert sent == ["Set that up — 08:30 daily."]


@pytest.mark.parametrize("intent,fragment", [
    ({"type": "schedule_create", "name": "x", "every": "daily", "at": "07:00"}, "body"),
    ({"type": "schedule_create", "name": "x", "every": "fortnightly",
      "at": "07:00", "body": "y"}, "fortnightly"),
    ({"type": "schedule_update", "name": "never-existed", "enabled": False}, "never-existed"),
])
def test_a_bad_schedule_is_refused_leaving_nothing_half_written(v2, intent, fragment):
    ex = run_intents(v2, intent)
    assert ex.problems and fragment in ex.problems[0]
    assert not (v2.config.SCHEDULES_DIR / "x.md").exists()


def test_a_name_cannot_become_a_path(v2):
    run_intents(v2, {"type": "schedule_create", "name": "../../escape",
                     "every": "daily", "at": "07:00", "body": "y"})
    assert (v2.config.SCHEDULES_DIR / "escape.md").exists()
    assert not (v2.config.MEMORY_DIR.parent / "escape.md").exists()


def test_update_carries_through_everything_she_did_not_name(v2):
    """`pause the digest` must not quietly discard the contract in the body."""
    write(v2, "digest", DAILY)
    run_intents(v2, {"type": "schedule_update", "name": "digest", "at": "07:45"})
    s = v2.schedules.get("digest")
    assert s.at == dtime(7, 45)
    assert s.produces == "projects/the_mirror/digest/{date}.txt"
    assert s.min_bytes == 500 and s.budget_usd == 4.0 and s.summary == "morning digest"
    assert "Write the digest to" in s.path.read_text()


def test_pausing_keeps_the_file_and_says_so(v2):
    sent = []
    write(v2, "digest", DAILY)
    run_intents(v2, {"type": "schedule_update", "name": "digest", "enabled": False},
                sent=sent)
    s = v2.schedules.get("digest")
    assert s.enabled is False
    assert "Write the digest to" in s.path.read_text()      # nothing deleted
    assert "will not fire until you turn it back on" in sent[0]


# ─── the tool catalog ───────────────────────────────────────────────────────

CARD = '''---
name: silicon-browser
binary: /opt/homebrew/bin/silicon-browser
summary: web pages, scrolling, screenshots, PDFs
---
The long manual a worker reads.
'''


def test_the_empty_catalog_still_names_the_folder(v2):
    """On the very first *add silicon-browser* there is no card to copy a path
    from, and an agent with no tools cannot go looking."""
    block = v2.tools_catalog.render()
    assert str(v2.config.TOOLS_DIR) in block
    assert "TOOLS" in block


def test_a_card_appears_in_the_index_with_its_path(v2):
    v2.config.TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    (v2.config.TOOLS_DIR / "silicon-browser.md").write_text(CARD)
    block = v2.tools_catalog.render()
    assert "silicon-browser" in block
    assert "web pages, scrolling, screenshots, PDFs" in block
    assert str(v2.config.TOOLS_DIR / "silicon-browser.md") in block
    assert "The long manual" not in block           # the index, not the manual


def test_a_broken_card_is_skipped_never_fatal(v2):
    v2.config.TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    (v2.config.TOOLS_DIR / "good.md").write_text(CARD)
    (v2.config.TOOLS_DIR / "bad.md").write_text("---\nname: [oops\n---\nx\n")
    cards = v2.tools_catalog.scan(trace=v2.trace.Trace())
    assert list(cards) == ["silicon-browser"]


def test_the_fingerprint_moves_when_a_card_changes(v2):
    v2.config.TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    before = v2.tools_catalog.fingerprint()
    (v2.config.TOOLS_DIR / "silicon-browser.md").write_text(CARD)
    assert v2.tools_catalog.fingerprint() != before


def test_a_worker_can_write_a_card_even_though_notes_cannot_be_routed_there(v2):
    """The asymmetry the design depends on: `_tools/` is unroutable, so a note
    can never land there, but a deliberate spawn's instruction is prose and the
    worker has Write — which is how bismuth adds a tool when she asks."""
    assert v2.destinations.resolve("_tools/x.md") is None
    ex = run_intents(v2, {"type": "spawn", "task_ref": None,
                          "instruction": f"Write {v2.config.TOOLS_DIR}/x.md"})
    assert ex.problems == [] and len(ex.spawns) == 1


# ─── the background thread ──────────────────────────────────────────────────

def test_one_failing_check_cannot_kill_the_others(v2, monkeypatch):
    """Pre-existing latent bug: one exception killed the thread and took audio
    push, git sync and the board with it, silently."""
    import threading
    import time as _time
    from v2.runtime import Runtime

    ran = {"audio": 0, "memory": 0, "board": 0, "schedules": 0}
    monkeypatch.setattr(v2.config, "AUDIO_PUSH_INTERVAL", 0)
    monkeypatch.setattr(v2.config, "MEMORY_SYNC_INTERVAL", 0)
    monkeypatch.setattr(v2.config, "BOARD_REFRESH_INTERVAL", 0)
    monkeypatch.setattr(v2.config, "SCHEDULE_TICK_INTERVAL", 0)

    import v2.archive, v2.gitsync, v2.schedules as sched
    monkeypatch.setattr(v2.archive, "push", lambda tr: ran.__setitem__("audio", ran["audio"] + 1))
    monkeypatch.setattr(v2.gitsync, "sync", lambda tr: ran.__setitem__("memory", ran["memory"] + 1))

    def boom(tr, now=None):
        ran["schedules"] += 1
        raise ValueError("a hand-edited schedule blew up")
    monkeypatch.setattr(sched, "tick", boom)

    rt = Runtime(dry_run=True)
    rt.refresh_board = lambda: ran.__setitem__("board", ran["board"] + 1)
    thread = threading.Thread(target=rt._background, daemon=True)
    thread.start()
    _time.sleep(6)
    rt.running = False
    thread.join(timeout=6)

    assert ran["schedules"] >= 1
    assert ran["audio"] >= 1 and ran["memory"] >= 1 and ran["board"] >= 1
    failures = [e for e in v2.trace.Trace.iter_events({"background_check_failed"})]
    assert failures and failures[-1]["check"] == "schedules"


# ─── the board reads the trace, never state.json ────────────────────────────

def test_the_board_panel_is_folded_from_the_trace(v2):
    import tools.board as board
    write(v2, "digest", DAILY)
    v2.schedules.tick(v2.trace.Trace(), now=at("2026-09-01T09:00"))
    sections = dict(v2.board_sections.build(board, v2.config.MEMORY_DIR))
    assert "SCHEDULES" in sections
    items = [i["text"] for i in sections["SCHEDULES"][0].cards[0].items]
    assert any("digest" in t and "daily at 08:30" in t for t in items)

    src = (Path(__file__).resolve().parent.parent / "v2" / "board_sections.py").read_text()
    assert "state.read" not in src and "import state" not in src
