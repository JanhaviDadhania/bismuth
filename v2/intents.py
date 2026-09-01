"""Executing the main agent's intents — §4.8.

The agent returns intents; the *runtime* performs them and writes a trace
event for each. That is what keeps the no-work rule intact while still letting
one turn create a task, ask a question and spawn three workers: `tasks.json`
is a projection of those events, never a file the agent edits.

Two things the runtime does itself rather than delegating, and both are
deliberate:

  * parking in `others/` — park-first must be atomic and cannot depend on a
    worker succeeding (§4.7);
  * sending Telegram messages — the agent has no tools, so every word she
    reads is text the runtime carries for it (§4.10).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from . import config as cfg
from . import destinations
from .tasks import Projection
from .trace import Trace

VALID_TYPES = {"route", "task_create", "task_ask", "task_clarify", "spawn",
               "task_done", "reply", "session_reset"}


@dataclass
class SpawnRequest:
    subagent_id: str
    task_id: str | None
    instruction: str
    kind: str = "write"
    budget_usd: float | None = None
    trace_id: str | None = None
    is_route: bool = False              # drives the ack when it finishes
    destination: str = ""               # what the ack reports as the landing place


@dataclass
class Execution:
    """What one turn actually did. The runtime acts on `spawns`; everything
    else has already happened by the time this returns."""
    spawns: list[SpawnRequest] = field(default_factory=list)
    replied: bool = False
    reset_requested: bool = False
    parked: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    task_ids: dict[str, str] = field(default_factory=dict)


def _slug(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (s[:limit] or "note")


def park_in_others(text: str, reason: str, trace_id: str | None,
                   trace: Trace) -> str:
    """Write the note to `others/` before anything else happens. This is the
    whole of park-first, and it is a plain file write on purpose: a question
    that never gets answered must not be able to lose the note, and neither
    must a worker that fails."""
    cfg.OTHERS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    path = cfg.OTHERS_DIR / f"{stamp}__{trace_id or 'note'}__{_slug(text)}.md"
    body = (f"# parked {datetime.now().astimezone().isoformat(timespec='seconds')}\n\n"
            f"{text}\n\n---\nreason: {reason}\ntrace_id: {trace_id}\n")
    path.write_text(body)
    trace.append("parked_in_others", trace_id=trace_id, path=str(path),
                 reason=reason, bytes=len(body.encode()))
    return str(path)


class Executor:
    def __init__(self, proj: Projection, trace: Trace,
                 send: Callable[[str], None],
                 send_voice: Callable[[str], None] | None = None):
        self.proj = proj
        self.trace = trace
        self.send = send
        self.send_voice = send_voice

    def run(self, intents: list[dict], item: dict) -> Execution:
        ex = Execution()
        trace_id = item.get("trace_id")
        note_text = item.get("text") or ""

        for raw in intents:
            if not isinstance(raw, dict):
                ex.problems.append(f"intent is not an object: {raw!r}")
                continue
            itype = raw.get("type")
            if itype not in VALID_TYPES:
                ex.problems.append(f"unknown intent type: {itype!r}")
                continue
            try:
                getattr(self, f"_do_{itype}")(raw, ex, trace_id, note_text)
            except Exception as exc:                      # never lose the turn
                ex.problems.append(f"{itype} failed: {exc}")
        return ex

    # ─── task id plumbing ───────────────────────────────────────────────────

    def _resolve_ref(self, ref: str | None, ex: Execution) -> str | None:
        """`task_ref` is either a real task_id from TASKS, or a label the agent
        invented for a task it created in this same turn (it cannot know an id
        the runtime has not assigned yet)."""
        if not ref:
            return None
        if ref in ex.task_ids:
            return ex.task_ids[ref]
        if ref in self.proj.live:
            return ref
        return None

    # ─── intents ────────────────────────────────────────────────────────────

    def _do_route(self, intent: dict, ex: Execution, trace_id, note_text):
        mode = intent.get("mode") or "inferred"
        destination = intent.get("destination") or ""
        reason = intent.get("reason") or ""
        instruction = intent.get("instruction") or ""

        resolved = destinations.resolve(destination) if mode != "unroutable" else None

        if mode == "unroutable" or resolved is None:
            if mode != "unroutable":
                # The agent named something not in DESTINATIONS. The guard is
                # the runtime's, not the model's — and the miss is recorded
                # rather than quietly corrected.
                self.trace.append("route_rejected", trace_id=trace_id,
                                  destination=destination, reason=reason)
                reason = f"{reason} [destination {destination!r} does not exist]"
            path = park_in_others(note_text or instruction, reason, trace_id, self.trace)
            ex.parked.append(path)
            self.trace.append("route_decided", trace_id=trace_id,
                              destination="others/", mode="unroutable",
                              reason=reason)
            return

        self.trace.append("route_decided", trace_id=trace_id,
                          destination=str(resolved), mode=mode, reason=reason)
        if not instruction:
            ex.problems.append("route intent carried no instruction")
            return
        sid = self.proj.next_subagent_id()
        instruction = self._with_claude_md(instruction, intent)
        kind = intent.get("kind") or "write"
        ex.spawns.append(SpawnRequest(
            subagent_id=sid, task_id=None, instruction=instruction, kind=kind,
            budget_usd=intent.get("budget_usd"), trace_id=trace_id,
            is_route=True, destination=str(resolved)))
        self.trace.append("subagent_spawned", trace_id=trace_id, task_id=None,
                          subagent_id=sid, instruction=instruction,
                          kind=kind, destination=str(resolved))
        # Tracked like any other worker, so a crash mid-write is caught by boot
        # reconciliation and she is told, rather than the note going quiet.
        self.proj.subagents[sid] = {"id": sid, "task_id": None,
                                    "instruction": instruction, "kind": kind,
                                    "status": "running", "result": None}

    def _do_task_create(self, intent: dict, ex: Execution, trace_id, note_text):
        task_id = self.proj.next_task_id()
        ref = intent.get("task_ref") or task_id
        ex.task_ids[ref] = task_id
        state = intent.get("state") if intent.get("state") in ("unclear", "working") else "unclear"
        event = self.trace.append("task_created", trace_id=trace_id,
                                  task_id=task_id, state=state,
                                  request=intent.get("request") or note_text)
        from .tasks import Task
        self.proj.live[task_id] = Task(task_id=task_id, state=state,
                                       request=intent.get("request") or note_text,
                                       created=event["ts"], trace_id=trace_id)

    def _do_task_ask(self, intent: dict, ex: Execution, trace_id, note_text):
        task_id = self._resolve_ref(intent.get("task_ref"), ex)
        question = intent.get("question") or ""
        if not task_id:
            ex.problems.append(f"task_ask for unknown task_ref {intent.get('task_ref')!r}")
            return
        if not question:
            ex.problems.append("task_ask with no question")
            return
        # The trace event is written BEFORE the send: park-first, ask-second,
        # for questions too.
        self.trace.append("task_question_asked", trace_id=trace_id,
                          task_id=task_id, question=question)
        task = self.proj.live.get(task_id)
        if task:
            task.question = question
            task.state = "unclear"
        self.send(question)
        ex.replied = True

    def _do_task_clarify(self, intent: dict, ex: Execution, trace_id, note_text):
        task_id = self._resolve_ref(intent.get("task_ref"), ex)
        if not task_id:
            ex.problems.append(f"task_clarify for unknown task_ref {intent.get('task_ref')!r}")
            return
        answer = intent.get("answer") or note_text
        self.trace.append("task_clarified", trace_id=trace_id, task_id=task_id,
                          answer=answer, new_state="working")
        task = self.proj.live.get(task_id)
        if task:
            task.answers.append({"ts": None, "text": answer})
            task.state = "working"
            task.question = None

    def _do_spawn(self, intent: dict, ex: Execution, trace_id, note_text):
        task_id = self._resolve_ref(intent.get("task_ref"), ex)
        instruction = intent.get("instruction") or ""
        if not instruction:
            ex.problems.append("spawn with no instruction")
            return
        sid = self.proj.next_subagent_id()
        kind = intent.get("kind") or "write"
        instruction = self._with_claude_md(instruction, intent)
        ex.spawns.append(SpawnRequest(subagent_id=sid, task_id=task_id,
                                      instruction=instruction, kind=kind,
                                      budget_usd=intent.get("budget_usd"),
                                      trace_id=trace_id))
        self.trace.append("subagent_spawned", trace_id=trace_id, task_id=task_id,
                          subagent_id=sid, instruction=instruction, kind=kind)
        record = {"id": sid, "task_id": task_id, "instruction": instruction,
                  "kind": kind, "status": "running", "result": None}
        self.proj.subagents[sid] = record
        task = self.proj.live.get(task_id) if task_id else None
        if task:
            task.subagents.append(record)
            task.state = "working"

    def _do_task_done(self, intent: dict, ex: Execution, trace_id, note_text):
        task_id = self._resolve_ref(intent.get("task_ref"), ex)
        if not task_id:
            ex.problems.append(f"task_done for unknown task_ref {intent.get('task_ref')!r}")
            return
        text = intent.get("text") or ""
        task = self.proj.live.get(task_id)
        self.trace.append("task_done", trace_id=trace_id, task_id=task_id,
                          request=(task.request if task else ""), text=text,
                          subagent_ids=[s["id"] for s in (task.subagents if task else [])])
        self.proj.live.pop(task_id, None)
        self.proj.done_tail.append({"task_id": task_id,
                                    "request": task.request if task else "",
                                    "ts": None, "text": text})
        if text:
            self.send(text)
            ex.replied = True

    def _do_reply(self, intent: dict, ex: Execution, trace_id, note_text):
        text = intent.get("text") or ""
        if not text:
            return
        channel = intent.get("channel") or "text"
        if channel == "voice" and self.send_voice:
            self.send_voice(text)
        else:
            self.send(text)
        self.trace.append("reply_sent", trace_id=trace_id, channel=channel,
                          kind="text", text=text)
        ex.replied = True

    def _do_session_reset(self, intent: dict, ex: Execution, trace_id, note_text):
        ex.reset_requested = True

    # ─── helper ─────────────────────────────────────────────────────────────

    @staticmethod
    def _with_claude_md(instruction: str, intent: dict) -> str:
        """§4.9.1's repair, made mechanical: if the agent named a CLAUDE.md,
        the worker is told to read it first, in the instruction itself."""
        path = intent.get("claude_md")
        if not path:
            return instruction
        return (f"First read {path} — it is the context for this folder.\n\n"
                f"{instruction}")
