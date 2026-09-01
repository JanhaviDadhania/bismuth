"""The main agent — §4.5. One session, one turn at a time, no tools.

`--tools ""` is the enforcement of the no-work rule, not a convention the
prompt asks it to respect: an agent with no file tools cannot quietly do the
work itself on a turn where delegating felt slow.

Measured 2026-09-01: 7,696 tokens of prefix per fresh session — 797 carrier,
2,896 for the intent schema, 4,003 for the prompt. The schema is the second
most expensive thing in the turn, and worth it for the reason below.

The turn returns intents as validated JSON via `--json-schema`, which arrives
in the result event's `structured_output` field, so the runtime never parses
prose hopefully.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field

from . import config as cfg
from . import destinations, state, tasks
from .tasks import Projection
from .trace import Trace


@dataclass
class TurnResult:
    intents: list[dict] = field(default_factory=list)
    session_id: str = ""
    tokens: int = 0
    cost_usd: float = 0.0
    duration_sec: float = 0.0
    error: str | None = None
    raw_text: str = ""


def render_others_block(limit: int = 20) -> str:
    """What is parked and unanswered. Surfaced every turn on purpose: v1 let
    113 messages rot in dead_letter/ because nothing ever showed them (§4.7)."""
    if not cfg.OTHERS_DIR.exists():
        return "OTHERS (0)"
    files = sorted(cfg.OTHERS_DIR.glob("*.md"))
    lines = [f"OTHERS ({len(files)}) — parked, destination unknown"]
    for f in files[-limit:]:
        first = ""
        try:
            first = next((l.strip() for l in f.read_text().splitlines()
                          if l.strip()), "")
        except OSError:
            pass
        lines.append(f"  {f.name}: {first[:120]}")
    return "\n".join(lines)


def build_turn_input(item: dict, proj: Projection, *, include_destinations: bool,
                     destinations_changed: bool = False) -> str:
    """Assemble the labelled blocks the prompt documents.

    DESTINATIONS is ~3.2k tokens, so it is sent on the first turn of a session
    and again only if the tree changed — not every turn. TASKS is sent every
    turn, which is what makes the 40% session reset survivable: the state was
    never held inside the session (§4.8).
    """
    blocks: list[str] = []

    if include_destinations:
        header = ("DESTINATIONS — the memory tree changed since the last turn; "
                  "this replaces the earlier list.\n" if destinations_changed else "")
        blocks.append(header + destinations.render())

    blocks.append(tasks.render_tasks_block(proj))
    blocks.append(tasks.render_recent_block(proj, cfg.DONE_TAIL))
    blocks.append(render_others_block())

    if item.get("kind") == "note":
        blocks.append("NOTE — from janhavi, just now"
                      + (f" (voice, transcribed)" if item.get("voice") else "")
                      + f"\n{item.get('text', '')}")
    elif item.get("kind") == "subagent_result":
        blocks.append(
            "SUBAGENT_RESULT — a worker you spawned has ended. She has not "
            "seen this.\n"
            f"  task: {item.get('task_id')}\n"
            f"  worker: {item.get('subagent_id')}\n"
            f"  you told it: {item.get('instruction', '')}\n"
            f"  {item.get('result', '')}"
        )
    elif item.get("kind") == "system":
        blocks.append(f"SYSTEM — the runtime is telling you something.\n{item.get('text','')}")

    return "\n\n".join(blocks)


def _command(turn_input: str, session_id: str, is_new: bool) -> list[str]:
    cmd = [
        "claude", "-p", turn_input,
        "--output-format", "stream-json", "--verbose",
        "--system-prompt", cfg.MAIN_AGENT_PROMPT.read_text(),
        "--tools", "",
        "--json-schema", cfg.INTENT_SCHEMA.read_text(),
        "--strict-mcp-config",
        "--disable-slash-commands",
    ]
    cmd += ["--session-id", session_id] if is_new else ["--resume", session_id]
    if cfg.MAIN_MODEL:
        cmd += ["--model", cfg.MAIN_MODEL]
    return cmd


def run_turn(item: dict, proj: Projection, *, session_id: str, is_new: bool,
             include_destinations: bool, destinations_changed: bool = False,
             trace: Trace | None = None) -> TurnResult:
    tr = trace or Trace()
    turn_input = build_turn_input(item, proj,
                                  include_destinations=include_destinations,
                                  destinations_changed=destinations_changed)
    started = time.time()
    trace_id = item.get("trace_id")
    result_obj = None
    final_text = ""

    try:
        proc = subprocess.Popen(
            _command(turn_input, session_id, is_new),
            cwd=str(cfg.SUBAGENT_CWD),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            tr.append("agent_event", trace_id=trace_id,
                      session_id=session_id, line=event)
            if event.get("type") == "result":
                result_obj = event
                final_text = event.get("result") or ""
        proc.wait(timeout=cfg.MAIN_AGENT_TIMEOUT)
        stderr = (proc.stderr.read() if proc.stderr else "") or ""
    except subprocess.TimeoutExpired:
        proc.kill()
        return TurnResult(session_id=session_id, error=f"turn timed out after "
                          f"{cfg.MAIN_AGENT_TIMEOUT}s",
                          duration_sec=time.time() - started)
    except Exception as exc:
        return TurnResult(session_id=session_id, error=f"turn failed: {exc}",
                          duration_sec=time.time() - started)

    duration = round(time.time() - started, 2)

    if result_obj is None:
        return TurnResult(session_id=session_id, duration_sec=duration,
                          error=f"no result event from claude -p; stderr: {stderr[:500]}")
    if result_obj.get("is_error"):
        return TurnResult(session_id=session_id, duration_sec=duration,
                          raw_text=final_text,
                          error=(result_obj.get("api_error_status")
                                 or final_text or "claude -p reported an error")[:1000])

    usage = result_obj.get("usage") or {}
    context_tokens = sum(int(usage.get(k) or 0) for k in
                         ("input_tokens", "cache_creation_input_tokens",
                          "cache_read_input_tokens", "output_tokens"))

    structured = result_obj.get("structured_output")
    if not isinstance(structured, dict):
        try:
            structured = json.loads(final_text)
        except (json.JSONDecodeError, TypeError):
            structured = None
    if not isinstance(structured, dict) or not isinstance(structured.get("intents"), list):
        return TurnResult(session_id=session_id, duration_sec=duration,
                          tokens=context_tokens, raw_text=final_text,
                          error="turn did not return {\"intents\": [...]}")

    window = cfg.CONTEXT_WINDOW
    tr.append("turn_usage", trace_id=trace_id, session_id=session_id,
              input_tokens=usage.get("input_tokens"),
              output_tokens=usage.get("output_tokens"),
              cache_read=usage.get("cache_read_input_tokens"),
              cache_creation=usage.get("cache_creation_input_tokens"),
              thinking_tokens=(usage.get("output_tokens_details") or {}).get("thinking_tokens"),
              running_total=context_tokens,
              window_size=window,
              pct_of_window=round(100 * context_tokens / window, 1),
              cost_usd=result_obj.get("total_cost_usd"),
              duration_sec=duration)

    return TurnResult(intents=structured["intents"], session_id=session_id,
                      tokens=context_tokens,
                      cost_usd=float(result_obj.get("total_cost_usd") or 0.0),
                      duration_sec=duration, raw_text=final_text)


def needs_reset(session: dict | None) -> bool:
    """Hard reset at 40% of the window, measured from claude -p's own numbers
    rather than estimated from characters (§4.5)."""
    if not session:
        return False
    window = session.get("window_size") or cfg.CONTEXT_WINDOW
    return (session.get("tokens") or 0) >= window * cfg.RESET_PCT
