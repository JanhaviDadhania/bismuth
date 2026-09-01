"""The task list — §4.8. A projection of the trace, not a second record.

Two live states, `unclear` and `working`. `done` is an event, not a state:
folding `task_done` drops the task from the live list, so nothing accumulates
and no cleanup daemon is needed. Every task that ever existed stays in the
trace with its question, her answers, and each worker's verbatim instruction.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from . import config as cfg
from .trace import Trace

LIVE_STATES = ("unclear", "working")
_ID_RE = re.compile(r"^t_(\d+)$")


@dataclass
class Task:
    task_id: str
    state: str
    request: str
    created: str
    trace_id: str | None = None
    question: str | None = None
    answers: list[dict] = field(default_factory=list)
    subagents: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id, "state": self.state,
            "trace_id": self.trace_id, "request": self.request,
            "created": self.created, "question": self.question,
            "answers": self.answers, "subagents": self.subagents,
        }

    def open_subagents(self) -> list[dict]:
        return [s for s in self.subagents if s.get("status") == "running"]

    def all_settled(self) -> bool:
        return bool(self.subagents) and not self.open_subagents()


@dataclass
class Projection:
    """Everything §4.8 needs, folded forward from the trace in one pass."""
    live: dict[str, Task] = field(default_factory=dict)
    done_tail: list[dict] = field(default_factory=list)
    subagents: dict[str, dict] = field(default_factory=dict)
    acks: list[dict] = field(default_factory=list)
    others: list[dict] = field(default_factory=list)
    max_task_num: int = 0
    max_subagent_num: int = 0

    # ─── ids ────────────────────────────────────────────────────────────────

    def next_task_id(self) -> str:
        self.max_task_num += 1
        return f"t_{self.max_task_num:04d}"

    def next_subagent_id(self) -> str:
        self.max_subagent_num += 1
        return f"sa_{self.max_subagent_num:04d}"

    # ─── views ──────────────────────────────────────────────────────────────

    def by_state(self, state: str) -> list[Task]:
        return [t for t in self.live.values() if t.state == state]

    def find_subagent_task(self, subagent_id: str) -> Task | None:
        for task in self.live.values():
            for sub in task.subagents:
                if sub.get("id") == subagent_id:
                    return task
        return None

    def to_cache(self) -> dict:
        return {
            "live": {k: v.to_dict() for k, v in self.live.items()},
            "done_tail": self.done_tail[-50:],
            "subagents": self.subagents,
            "acks": self.acks[-100:],
        }


def _track_num(pattern: re.Pattern, value: str, current: int) -> int:
    m = pattern.match(value or "")
    return max(current, int(m.group(1))) if m else current


_SA_RE = re.compile(r"^sa_(\d+)$")


def fold(events=None) -> Projection:
    """Rebuild the live task list from the trace. Cheap enough to run at boot;
    the tier-2 cache exists so a restart is fast, never because it is true."""
    proj = Projection()
    for e in (events if events is not None else Trace.iter_events()):
        etype = e.get("type")

        if etype == "task_created":
            tid = e.get("task_id") or ""
            proj.max_task_num = _track_num(_ID_RE, tid, proj.max_task_num)
            proj.live[tid] = Task(
                task_id=tid,
                state=e.get("state") or "unclear",
                request=e.get("request") or "",
                created=e.get("ts") or "",
                trace_id=e.get("trace_id"),
            )

        elif etype == "task_question_asked":
            task = proj.live.get(e.get("task_id"))
            if task:
                task.question = e.get("question")
                task.state = "unclear"

        elif etype == "task_clarified":
            task = proj.live.get(e.get("task_id"))
            if task:
                task.answers.append({"ts": e.get("ts"), "text": e.get("answer")})
                task.state = e.get("new_state") or "working"
                task.question = None

        elif etype == "subagent_spawned":
            sid = e.get("subagent_id") or ""
            proj.max_subagent_num = _track_num(_SA_RE, sid, proj.max_subagent_num)
            record = {
                "id": sid, "task_id": e.get("task_id"),
                "instruction": e.get("instruction") or "",
                "kind": e.get("kind") or "write",
                "status": "running", "result": None,
            }
            proj.subagents[sid] = record
            task = proj.live.get(e.get("task_id"))
            if task:
                task.subagents.append(record)
                task.state = "working"

        elif etype in ("subagent_done", "subagent_failed"):
            sid = e.get("subagent_id") or ""
            record = proj.subagents.get(sid)
            if record:
                record["status"] = e.get("status") or (
                    "done" if etype == "subagent_done" else "failed")
                record["result"] = e.get("summary") or e.get("error") or e.get("question")

        elif etype == "task_blocked":
            task = proj.live.get(e.get("task_id"))
            if task:
                task.state = "unclear"

        elif etype == "task_done":
            task = proj.live.pop(e.get("task_id"), None)
            proj.done_tail.append({
                "task_id": e.get("task_id"),
                "request": (task.request if task else e.get("request") or ""),
                "ts": e.get("ts"),
                "text": e.get("text") or "",
            })

        elif etype == "ack":
            proj.acks.append({
                "ts": e.get("ts"), "trace_id": e.get("trace_id"),
                "status": e.get("status"), "transcript": e.get("transcript"),
                "destinations": e.get("destinations") or [],
            })

        elif etype == "parked_in_others":
            proj.others.append({"ts": e.get("ts"), "path": e.get("path"),
                                "reason": e.get("reason"),
                                "trace_id": e.get("trace_id")})

    return proj


def save_cache(proj: Projection) -> None:
    """Tier 2 — written so a restart is fast. Deleting it loses nothing."""
    cfg.ensure_dirs()
    cfg.TASKS_CACHE.write_text(json.dumps(proj.to_cache(), indent=2, ensure_ascii=False))
    cfg.SUBAGENTS_CACHE.write_text(json.dumps(proj.subagents, indent=2, ensure_ascii=False))


# ─── rendering for the main agent turn (§4.8: the list is injected every turn)

def render_tasks_block(proj: Projection) -> str:
    if not proj.live:
        return "TASKS\n  (none open)"
    lines = ["TASKS"]
    for state in LIVE_STATES:
        tasks = proj.by_state(state)
        if not tasks:
            continue
        lines.append(f"  {state.upper()} ({len(tasks)})")
        for t in tasks:
            lines.append(f"    [{t.task_id}] {t.request}")
            if t.question:
                lines.append(f"        asked her: {t.question}")
            for a in t.answers:
                lines.append(f"        she answered: {a.get('text')}")
            for s in t.subagents:
                bit = f"        worker {s['id']} [{s['status']}]"
                if s.get("result"):
                    bit += f" — {s['result']}"
                lines.append(bit)
                lines.append(f"            was told: {s['instruction']}")
    return "\n".join(lines)


def render_recent_block(proj: Projection, limit: int) -> str:
    tail = proj.done_tail[-limit:]
    if not tail:
        return "RECENT\n  (nothing completed yet)"
    lines = ["RECENT (last completed — what \"the thing you just did\" means)"]
    for d in tail:
        lines.append(f"  [{d['task_id']}] {d['request']}  — {d['ts']}")
    return "\n".join(lines)
