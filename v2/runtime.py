"""The runtime — one queue, one turn at a time, one voice.

Boot: fold the trace, reconcile anything the last crash left running, then
serve. The main loop is deliberately small; everything it does is either
described in §4 of the architecture or is not done at all.
"""

from __future__ import annotations

import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import config as cfg
from . import (archive, destinations, gitsync, ingest, intents, mainagent,
               schedules, state, subagent, tasks, tg, tools_catalog)
from .intents import SpawnRequest
from .tasks import Projection
from .trace import Trace


@dataclass
class RouteContext:
    """What an ack needs when the writing worker finishes (§4.11)."""
    trace_id: str | None
    transcript: str
    destination: str


class Runtime:
    def __init__(self, dry_run: bool = False):
        self.trace = Trace()
        self.dry_run = dry_run
        self.proj: Projection = Projection()
        self.pool = ThreadPoolExecutor(max_workers=cfg.MAX_CONCURRENT_SUBAGENTS,
                                       thread_name_prefix="subagent")
        self.wake = threading.Event()
        self.running = True
        self.poller: ingest.Poller | None = None
        self.route_ctx: dict[str, RouteContext] = {}
        self.dest_fingerprint: str | None = None
        self.pending_reset_ids: set[str] = set()
        self.sent: list[str] = []            # dry-run transcript of her channel

    # ─── outbound: one voice (§4.10) ────────────────────────────────────────

    def send(self, text: str) -> None:
        self.sent.append(text)
        if self.dry_run:
            print(f"\n  ┌─ to janhavi ─\n  │ " + text.replace("\n", "\n  │ ") + "\n  └─")
            return
        try:
            tg.send_message(text)
        except Exception as exc:
            self.trace.append("reply_failed", error=str(exc)[:400], text=text[:500])

    def send_voice(self, text: str) -> None:
        """macOS `say` → a real Telegram voice note. Falls back to text rather
        than losing the message."""
        if self.dry_run:
            return self.send(f"[voice] {text}")
        import subprocess
        import tempfile
        try:
            with tempfile.TemporaryDirectory() as tmp:
                aiff = f"{tmp}/reply.aiff"
                ogg = f"{tmp}/reply.ogg"
                subprocess.run(["say", "-o", aiff, text], check=True, timeout=120)
                subprocess.run(["ffmpeg", "-y", "-i", aiff, "-c:a", "libopus", ogg],
                               check=True, capture_output=True, timeout=120)
                from pathlib import Path
                tg.send_voice(Path(ogg))
            self.trace.append("reply_sent", channel="voice", kind="voice", text=text)
        except Exception as exc:
            self.trace.append("voice_reply_failed", error=str(exc)[:300])
            self.send(text)

    # ─── boot — §6 ──────────────────────────────────────────────────────────

    def boot(self) -> None:
        cfg.ensure_dirs()
        self.proj = tasks.fold()
        self.reconcile()
        tasks.save_cache(self.proj)
        self.trace.append("runtime_started",
                          live_tasks=len(self.proj.live),
                          queued_turns=state.queue_depth(),
                          spooled=len(ingest.spooled()),
                          dry_run=self.dry_run)

    def reconcile(self) -> None:
        """A worker with a `subagent_spawned` event and no terminal event was
        killed by the crash — its process went with tier 3. Mark it failed,
        return its task to `unclear`, and make sure she is told. This is the
        step that stops v2 accumulating v1's 113 silent dead letters."""
        orphans = [s for s in self.proj.subagents.values() if s.get("status") == "running"]
        for record in orphans:
            sid = record["id"]
            self.trace.append("subagent_failed", trace_id=None, subagent_id=sid,
                              status="failed", error="runtime restart — worker died with the process",
                              reason="runtime restart")
            record["status"] = "failed"
            record["result"] = "died when the runtime restarted"
            task = self.proj.live.get(record.get("task_id")) if record.get("task_id") else None
            if task:
                task.state = "unclear"
                self.trace.append("task_blocked", task_id=task.task_id,
                                  subagent_id=sid, question="worker died on restart")
            state.enqueue_turn({
                "kind": "subagent_result", "trace_id": None,
                "task_id": record.get("task_id"), "subagent_id": sid,
                "instruction": record.get("instruction", ""),
                "result": ("status: failed\nerror: this worker was killed when the "
                           "runtime restarted. Decide whether to spawn it again."),
            })
        if orphans:
            self.trace.append("boot_reconciled", orphans=[o["id"] for o in orphans])

    # ─── the loop ───────────────────────────────────────────────────────────

    def serve(self) -> None:
        self.boot()
        problems = cfg.check()
        if problems and not self.dry_run:
            for p in problems:
                print(f"  ! {p}")
            self.trace.append("runtime_preflight_failed", problems=problems)
            raise SystemExit(1)

        if not self.dry_run:
            self.poller = ingest.Poller(self.trace, on_message=self.wake.set)
            self.poller.start()
            threading.Thread(target=self._background, daemon=True,
                             name="background").start()

        signal.signal(signal.SIGINT, self._signal)
        signal.signal(signal.SIGTERM, self._signal)

        while self.running:
            try:
                ingest.drain_spool(self.trace)
                item = state.dequeue_turn()
                if item is None:
                    self.wake.wait(timeout=2)
                    self.wake.clear()
                    continue
                self.process_turn(item)
            except Exception as exc:
                self.trace.append("loop_error", error=str(exc)[:800])
                time.sleep(1)

        self.trace.append("runtime_stopped")

    def _signal(self, *_):
        self.running = False
        self.wake.set()
        if self.poller:
            self.poller.stop()

    def _background(self) -> None:
        """The clock. Four independent checks on one 5s loop.

        **Each is wrapped separately, and that is not defensive habit.** One
        uncaught exception here kills the whole thread, and with it audio
        archiving, the memory git sync and the board — silently, since nothing
        else watches this thread. That was already latent; `_schedules/` makes
        it live, because a hand-edited schedule file can throw in `parse()`.
        A check that fails is traced and retried on its next interval; it can
        no longer take the other three down with it.
        """
        last = {"audio": 0.0, "memory": 0.0, "board": 0.0, "schedules": 0.0}
        checks = (
            ("audio", cfg.AUDIO_PUSH_INTERVAL, lambda: archive.push(self.trace)),
            ("memory", cfg.MEMORY_SYNC_INTERVAL, lambda: gitsync.sync(self.trace)),
            ("board", cfg.BOARD_REFRESH_INTERVAL, self.refresh_board),
            ("schedules", cfg.SCHEDULE_TICK_INTERVAL, self._schedule_tick),
        )
        while self.running:
            now = time.time()
            for name, interval, run in checks:
                if now - last[name] <= interval:
                    continue
                last[name] = now
                try:
                    run()
                except Exception as exc:
                    self.trace.append("background_check_failed", check=name,
                                      error=str(exc)[:600])
            time.sleep(5)

    def _schedule_tick(self) -> None:
        """Fire what is due, then ask whether the last firing actually produced
        the file it promised. `self.wake.set()` so the main loop picks the turn
        up now instead of waiting out its 2s timeout — schedules do not
        preempt, but they should not idle either."""
        fired = schedules.tick(self.trace)
        overdue = schedules.check_overdue(self.trace)
        if fired or overdue:
            self.wake.set()

    def refresh_board(self) -> None:
        import subprocess
        try:
            subprocess.run(["python3", str(cfg.BASE_DIR / "tools" / "board.py")],
                           capture_output=True, timeout=180)
        except Exception as exc:
            self.trace.append("board_refresh_failed", error=str(exc)[:300])

    # ─── one turn — §4.5 ────────────────────────────────────────────────────

    def process_turn(self, item: dict) -> None:
        session, is_new = self._session()
        # One fingerprint over the memory tree AND the tool catalog. Folding
        # them is simpler than a parallel flag, and either changing is the same
        # event as far as the turn is concerned: something the agent was told
        # exists no longer matches reality.
        fingerprint = f"{destinations.fingerprint()}+{tools_catalog.fingerprint()}"
        changed = self.dest_fingerprint is not None and fingerprint != self.dest_fingerprint
        include_ctx = is_new or changed
        if include_ctx:
            self.dest_fingerprint = fingerprint

        result = mainagent.run_turn(
            item, self.proj, session_id=session["id"], is_new=is_new,
            include_context=include_ctx, context_changed=changed,
            trace=self.trace)

        if result.error:
            self._turn_failed(item, result.error)
            return

        updated = state.record_turn_usage(result.tokens)
        execution = intents.Executor(self.proj, self.trace, self.send,
                                     self.send_voice).run(result.intents, item)

        if item.get("kind") == "note":
            self._maybe_ack_immediately(item, execution)
        for problem in execution.problems:
            self.trace.append("intent_problem", trace_id=item.get("trace_id"),
                              problem=problem)

        for spawn in execution.spawns:
            if spawn.is_route:
                self.route_ctx[spawn.subagent_id] = RouteContext(
                    trace_id=spawn.trace_id, transcript=item.get("text", ""),
                    destination=spawn.destination)
            self.pool.submit(self._run_subagent, spawn)

        if execution.reset_requested:
            self.pending_reset_ids = {s.subagent_id for s in execution.spawns}
            with state.mutate() as s:
                s["pending_reset"] = {"reason": "requested"}
            self._maybe_reset()

        tasks.save_cache(self.proj)
        if mainagent.needs_reset(updated):
            self._reset_session("context_40pct")

    def _turn_failed(self, item: dict, error: str) -> None:
        """A failure she can see. Never a silent dead-letter (§4.2)."""
        self.trace.append("turn_failed", trace_id=item.get("trace_id"), error=error)
        state.queue_retry({"item": item, "error": error})
        preview = (item.get("text") or "")[:200]
        self.send("Something broke while I was processing your last message, so "
                  "it is not filed yet. It is safe — I still have it, and it is "
                  f"in the retry queue.\n\nWhat you said: {preview}\n\nError: {error[:300]}")

    def _maybe_ack_immediately(self, item: dict, execution) -> None:
        """Parked notes ack now; routed ones ack when the worker reports (§4.5:
        the ack is slower in exchange for the turn being short)."""
        if execution.parked:
            self.trace.append("ack", trace_id=item.get("trace_id"), status="others",
                              transcript=item.get("text", ""),
                              destinations=[{"path": p, "action": "parked"}
                                            for p in execution.parked],
                              on_board=True)

    # ─── sessions — §4.5 ────────────────────────────────────────────────────

    def _session(self) -> tuple[dict, bool]:
        session = state.get_session()
        if session:
            return session, False
        session = state.start_session(cfg.CONTEXT_WINDOW)
        self.trace.append("session_started", session_id=session["id"],
                          window_size=session["window_size"])
        self.dest_fingerprint = None
        return session, True

    def _reset_session(self, reason: str) -> None:
        old = state.clear_session()
        self.trace.append("session_reset", reason=reason,
                          old_session=(old or {}).get("id"),
                          window_size=(old or {}).get("window_size"),
                          tokens=(old or {}).get("tokens"))
        self.dest_fingerprint = None

    def _maybe_reset(self) -> None:
        """A requested reset waits until the current note is fully processed —
        workers finished, replies sent (§4.5)."""
        if self.pending_reset_ids:
            return
        pending = state.read().get("pending_reset")
        if pending:
            with state.mutate() as s:
                s["pending_reset"] = None
            self._reset_session(pending.get("reason", "requested"))

    # ─── sub-agents — §4.9 ──────────────────────────────────────────────────

    def _run_subagent(self, spawn: SpawnRequest) -> None:
        result = subagent.run(spawn.instruction, spawn.subagent_id,
                              trace_id=spawn.trace_id, budget_usd=spawn.budget_usd,
                              trace=self.trace)
        event = "subagent_done" if result.status == "done" else "subagent_failed"
        self.trace.append(event, trace_id=spawn.trace_id,
                          subagent_id=spawn.subagent_id, task_id=spawn.task_id,
                          status=result.status, summary=result.summary,
                          output=result.output, question=result.question,
                          error=result.error, cost_usd=result.cost_usd,
                          tokens=result.tokens, duration_sec=result.duration_sec)

        record = self.proj.subagents.get(spawn.subagent_id)
        if record:
            record["status"] = result.status
            record["result"] = result.summary or result.question or result.error

        ctx = self.route_ctx.pop(spawn.subagent_id, None)
        if ctx:
            self.trace.append("ack", trace_id=ctx.trace_id,
                              status="saved" if result.status == "done" else "failed",
                              transcript=ctx.transcript,
                              destinations=[{"path": ctx.destination,
                                             "action": spawn.kind}],
                              on_board=True)

        # Wake the main agent only when there is a judgement to make. A plain
        # note-filing worker that succeeded has nothing for it to decide, and
        # a turn per note would make her wait for nothing.
        wake_needed = result.status != "done" or spawn.task_id is not None
        if wake_needed:
            state.enqueue_turn({                    # durable BEFORE the thread ends
                "kind": "subagent_result", "trace_id": spawn.trace_id,
                "task_id": spawn.task_id, "subagent_id": spawn.subagent_id,
                "instruction": spawn.instruction, "result": result.relay(),
            })
        self.pending_reset_ids.discard(spawn.subagent_id)
        self._maybe_reset()
        self.wake.set()


def main(dry_run: bool = False) -> None:
    Runtime(dry_run=dry_run).serve()
