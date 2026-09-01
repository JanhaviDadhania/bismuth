"""Entry point.

    python3 -m v2 serve                 # the real thing: Telegram in and out
    python3 -m v2 feed "text"           # offline: inject a note, print her side
    python3 -m v2 status                # queue, tasks, session, trace health
    python3 -m v2 check                 # preflight only
    python3 -m v2 destinations          # what the agent is told exists
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import config as cfg
from . import destinations as dest
from . import ingest, state, tasks
from .runtime import Runtime
from .trace import Trace


def cmd_serve(args) -> int:
    print(f"bismuth v2 — memory {cfg.MEMORY_DIR}, runtime {cfg.RUNTIME_DIR}")
    Runtime(dry_run=False).serve()
    return 0


def cmd_feed(args) -> int:
    """Run one note through the real agents without Telegram. Replies are
    printed instead of sent, so this is safe to point at a scratch tree."""
    rt = Runtime(dry_run=True)
    rt.boot()
    item = {"kind": "note", "trace_id": f"feed_{int(time.time())}",
            "text": args.text, "voice": False}
    print(f"\n  ┌─ from janhavi ─\n  │ {args.text}\n  └─")
    rt.process_turn(item)

    deadline = time.time() + args.wait
    while time.time() < deadline:
        pending = [s for s in rt.proj.subagents.values() if s.get("status") == "running"]
        queued = state.read().get("turn_queue") or []
        if not pending and not queued:
            break
        nxt = state.dequeue_turn()
        if nxt:
            print(f"\n  ·· waking the main agent: {nxt.get('kind')} "
                  f"{nxt.get('subagent_id') or ''}")
            rt.process_turn(nxt)
        else:
            time.sleep(1)

    print("\n── after ──")
    print(tasks.render_tasks_block(rt.proj))
    for sid, rec in rt.proj.subagents.items():
        print(f"  {sid} [{rec['status']}] {rec['instruction'][:110]}")
    return 0


def cmd_status(args) -> int:
    s = state.read()
    proj = tasks.fold()
    session = s.get("session") or {}
    window = session.get("window_size") or cfg.CONTEXT_WINDOW
    pct = round(100 * (session.get("tokens") or 0) / window, 1) if session else 0
    print(f"queue        {len(s.get('turn_queue') or [])} waiting")
    print(f"spool        {len(ingest.spooled())} unprocessed updates")
    print(f"retry        {len(s.get('retry') or [])} (visible, never dropped)")
    print(f"offset       {s.get('offset')}")
    print(f"session      {session.get('id', '—')}  {pct}% of window "
          f"(reset at {int(cfg.RESET_PCT * 100)}%)")
    print(f"tasks        {len(proj.by_state('unclear'))} unclear, "
          f"{len(proj.by_state('working'))} working")
    for t in proj.live.values():
        print(f"   [{t.task_id}] {t.state:8} {t.request[:70]}")
    others = sorted(cfg.OTHERS_DIR.glob("*.md")) if cfg.OTHERS_DIR.exists() else []
    print(f"others/      {len(others)} parked")
    gaps = Trace.seq_gaps()
    print(f"trace        {'complete' if not gaps else f'GAPS: {gaps}'}")
    return 0


def cmd_check(args) -> int:
    problems = cfg.check()
    if not problems:
        print("preflight ok")
        return 0
    for p in problems:
        print(f"  ! {p}")
    return 1


def cmd_destinations(args) -> int:
    block = dest.render()
    print(block)
    print(f"\n[{len(block)} chars, ~{round(len(block) / 3.2)} tokens, "
          f"fingerprint {dest.fingerprint()}]")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="v2", description="bismuth v2")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve").set_defaults(func=cmd_serve)
    feed = sub.add_parser("feed")
    feed.add_argument("text")
    feed.add_argument("--wait", type=int, default=240,
                      help="seconds to keep draining sub-agent results")
    feed.set_defaults(func=cmd_feed)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("check").set_defaults(func=cmd_check)
    sub.add_parser("destinations").set_defaults(func=cmd_destinations)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
