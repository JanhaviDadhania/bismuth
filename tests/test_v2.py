"""v2 tests — the paths that must not break quietly.

Run: python3 -m pytest tests/test_v2.py -q
Everything here runs against a throwaway tree via BISMUTH2_* env overrides;
nothing touches her real memory, and no test spends money on `claude -p`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The `v2` fixture lives in conftest.py — test_v2_schedules.py needs it too.


# ─── trace — §5 ─────────────────────────────────────────────────────────────

def test_seq_is_gapless_and_monotonic(v2):
    tr = v2.trace.Trace()
    seqs = [tr.append("probe", trace_id="u1", n=i)["seq"] for i in range(5)]
    assert seqs == sorted(seqs) == list(range(1, 6))
    assert v2.trace.Trace.seq_gaps() == []


def test_seq_survives_a_lost_counter(v2):
    """The counter file is a cache. If it is deleted, seq must not restart and
    collide — a duplicate seq would silently break the trace's ordering."""
    tr = v2.trace.Trace()
    for _ in range(3):
        tr.append("probe", trace_id="u1")
    v2.config.TRACE_SEQ_FILE.unlink()
    assert tr.append("probe", trace_id="u1")["seq"] == 4


def test_event_cap_marks_truncation(v2):
    tr = v2.trace.Trace(event_cap=50)
    event = tr.append("probe", trace_id="u1", blob="x" * 500)
    assert "truncated" in event["blob"] and len(event["blob"]) < 200


# ─── state — §6 ─────────────────────────────────────────────────────────────

def test_turn_queue_is_fifo_and_durable(v2):
    v2.state.enqueue_turn({"kind": "note", "text": "first"})
    v2.state.enqueue_turn({"kind": "subagent_result", "subagent_id": "sa_1"})
    assert json.loads(v2.config.STATE_FILE.read_text())["turn_queue"][0]["text"] == "first"
    assert v2.state.dequeue_turn()["text"] == "first"
    assert v2.state.dequeue_turn()["kind"] == "subagent_result"
    assert v2.state.dequeue_turn() is None


def test_dedup_ledger(v2):
    assert not v2.state.already_processed(884213)
    v2.state.mark_processed(884213)
    assert v2.state.already_processed(884213)


# ─── the task list — §4.8 ───────────────────────────────────────────────────

def _events():
    return [
        {"type": "task_created", "ts": "T1", "task_id": "t_0001",
         "state": "unclear", "request": "collage refs"},
        {"type": "task_question_asked", "ts": "T2", "task_id": "t_0001",
         "question": "which page?"},
        {"type": "task_clarified", "ts": "T3", "task_id": "t_0001",
         "answer": "the collage one", "new_state": "working"},
        {"type": "subagent_spawned", "ts": "T4", "task_id": "t_0001",
         "subagent_id": "sa_0001", "instruction": "append X"},
    ]


def test_done_is_an_event_not_a_state(v2):
    """Folding task_done drops the task from the live list — which is why no
    cleanup daemon is needed and nothing can accumulate."""
    proj = v2.tasks.fold(_events() + [
        {"type": "subagent_done", "ts": "T5", "subagent_id": "sa_0001", "status": "done"},
        {"type": "task_done", "ts": "T6", "task_id": "t_0001"},
    ])
    assert proj.live == {}
    assert proj.done_tail[-1]["request"] == "collage refs"


def test_needs_input_returns_the_task_to_unclear(v2):
    proj = v2.tasks.fold(_events() + [
        {"type": "subagent_done", "ts": "T5", "subagent_id": "sa_0001",
         "status": "needs_input", "question": "bullets or a table?"},
        {"type": "task_blocked", "ts": "T6", "task_id": "t_0001",
         "subagent_id": "sa_0001"},
    ])
    assert proj.live["t_0001"].state == "unclear"


def test_ids_never_collide_after_a_restart(v2):
    proj = v2.tasks.fold(_events())
    assert proj.next_task_id() == "t_0002"
    assert proj.next_subagent_id() == "sa_0002"


# ─── routing — §4.6 ─────────────────────────────────────────────────────────

def test_destination_must_exist(v2):
    assert v2.destinations.resolve("projects/the_mirror/nexttodo.md") is not None
    assert v2.destinations.resolve("projects/the_mirror/new_file.md") is not None
    assert v2.destinations.resolve("projects/ghost/x.md") is None
    assert v2.destinations.resolve("../../etc/passwd") is None


def test_invented_destination_parks_instead_of_writing(v2):
    """The hard guard is the runtime's, not the model's: an invented folder
    must never become a file write, and the miss must be recorded."""
    tr = v2.trace.Trace()
    sent = []
    ex = v2.intents.Executor(v2.tasks.fold([]), tr, sent.append)
    out = ex.run([{"type": "route", "destination": "projects/ghost/x.md",
                   "mode": "inferred", "reason": "guessed",
                   "instruction": "append Y"}],
                 {"trace_id": "u1", "text": "the note itself"})
    assert out.spawns == [] and len(out.parked) == 1
    types = [e["type"] for e in v2.trace.Trace.iter_events()]
    assert "route_rejected" in types and "parked_in_others" in types
    assert "the note itself" in Path(out.parked[0]).read_text()


def test_park_writes_before_the_question_is_asked(v2):
    """Park-first: the note is on disk before any question, so a question that
    is never answered cannot lose it."""
    tr = v2.trace.Trace()
    ex = v2.intents.Executor(v2.tasks.fold([]), tr, lambda t: None)
    ex.run([{"type": "route", "mode": "unroutable", "reason": "no such project",
             "instruction": ""},
            {"type": "task_create", "task_ref": "a", "request": "find a home",
             "state": "unclear"},
            {"type": "task_ask", "task_ref": "a", "question": "where?"}],
           {"trace_id": "u1", "text": "tomatoes are entangled"})
    order = [e["type"] for e in v2.trace.Trace.iter_events()]
    assert order.index("parked_in_others") < order.index("task_question_asked")


# ─── intents — §4.8 ─────────────────────────────────────────────────────────

def test_task_ref_label_maps_to_a_real_id(v2):
    tr = v2.trace.Trace()
    sent = []
    ex = v2.intents.Executor(v2.tasks.fold([]), tr, sent.append)
    out = ex.run([{"type": "task_create", "task_ref": "a", "request": "x",
                   "state": "unclear"},
                  {"type": "task_ask", "task_ref": "a", "question": "which one?"}],
                 {"trace_id": "u1", "text": "x"})
    assert out.task_ids == {"a": "t_0001"} and sent == ["which one?"]
    assert not out.problems


def test_unknown_intent_is_reported_not_swallowed(v2):
    ex = v2.intents.Executor(v2.tasks.fold([]), v2.trace.Trace(), lambda t: None)
    out = ex.run([{"type": "teleport"}, {"type": "task_ask", "task_ref": "nope",
                                         "question": "?"}],
                 {"trace_id": "u1", "text": ""})
    assert len(out.problems) == 2


# ─── sub-agent contract — §4.9 ──────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ('{"status":"done","summary":"ok"}', "done"),
    ('```json\n{"status":"needs_input","question":"which?"}\n```', "needs_input"),
    ('prose then {"status":"failed","error":"boom"}', "failed"),
])
def test_terminal_status_parsing(v2, text, expected):
    assert v2.subagent.parse_final(text)["status"] == expected


def test_unparseable_result_is_not_guessed(v2):
    """An unreadable return becomes `failed`, which is visible — never a
    silently-assumed success (issue #18 is bad enough already)."""
    assert v2.subagent.parse_final("I appended the line.") is None


def test_spawn_command_is_the_stripped_one(v2):
    cmd = v2.subagent.build_command("do the thing")
    assert cmd[:2] == ["claude", "-p"]
    assert "--strict-mcp-config" in cmd and "--disable-slash-commands" in cmd
    assert cmd[cmd.index("--tools") + 1] == "Read,Write,Edit,Bash"
    assert "--max-budget-usd" in cmd
    assert cmd[cmd.index("--effort") + 1] == "low"     # never thinking-disabled


# ─── the turn — §4.5 ────────────────────────────────────────────────────────

def test_destinations_block_is_sent_once_per_session_not_per_turn(v2):
    proj = v2.tasks.fold([])
    with_block = v2.mainagent.build_turn_input({"kind": "note", "text": "hi"},
                                               proj, include_context=True)
    without = v2.mainagent.build_turn_input({"kind": "note", "text": "hi"},
                                            proj, include_context=False)
    assert "DESTINATIONS" in with_block and "DESTINATIONS" not in without
    assert "TASKS" in without and "NOTE" in without


def test_tools_block_rides_the_same_gate_as_destinations(v2):
    """One flag, not two — and one fingerprint, so a tool appearing re-sends
    the pair rather than needing a parallel mechanism."""
    proj = v2.tasks.fold([])
    gated = v2.mainagent.build_turn_input({"kind": "note", "text": "hi"}, proj,
                                          include_context=True)
    ungated = v2.mainagent.build_turn_input({"kind": "note", "text": "hi"}, proj,
                                            include_context=False)
    assert "TOOLS" in gated and "TOOLS" not in ungated


def test_subagent_result_is_labelled_as_unseen_by_her(v2):
    block = v2.mainagent.build_turn_input(
        {"kind": "subagent_result", "task_id": "t_1", "subagent_id": "sa_1",
         "instruction": "append X", "result": "status: failed"},
        v2.tasks.fold([]), include_context=False)
    assert "She has not seen this" in block


def test_reset_fires_at_forty_percent(v2):
    window = v2.config.CONTEXT_WINDOW
    assert not v2.mainagent.needs_reset({"tokens": int(window * 0.39),
                                         "window_size": window})
    assert v2.mainagent.needs_reset({"tokens": int(window * 0.41),
                                     "window_size": window})


# ─── ingest — §4.2 ──────────────────────────────────────────────────────────

def test_spool_is_durable_before_the_offset_moves(v2):
    update = {"update_id": 884213, "message": {"text": "hi", "date": 1}}
    path = v2.ingest.spool(update)
    assert path.exists()
    assert json.loads(path.read_text())["update_id"] == 884213
    assert v2.state.read()["offset"] == 0    # untouched until the caller moves it


def test_redelivery_is_a_noop(v2):
    v2.ingest.spool({"update_id": 5, "message": {"text": "hi"}})
    v2.state.mark_processed(5)
    assert v2.ingest.drain_spool(v2.trace.Trace()) == []
    assert v2.state.queue_depth() == 0
