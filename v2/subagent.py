"""Sub-agents — §4.9, §4.9.1. `claude -p`, stripped bare.

Measured on 2026-08-31: a default spawn carries 27,398 tokens of prefix before
the instruction is read, more than half of it built-in tool schemas. The
stripped config below measures 5,063 with the real prompt — an 81.5%
reduction. Cutting tools also removes expensive *paths*: the same one-line file
append cost 118,011 tokens through Bash on a default spawn and 8,092 through
Read+Edit on this one.

A sub-agent has exactly three ways to end: done, needs_input, failed. It never
messages Janhavi; its return value is read by the main agent, which decides
what to relay (§4.8).
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import config as cfg
from .trace import Trace


@dataclass
class SubagentResult:
    subagent_id: str
    status: str                 # done | needs_input | failed
    summary: str = ""
    output: str = ""
    question: str = ""
    error: str = ""
    cost_usd: float = 0.0
    tokens: int = 0
    duration_sec: float = 0.0

    def relay(self) -> str:
        """What the main agent sees. Never sent to her as-is (§4.10)."""
        bits = [f"status: {self.status}"]
        if self.summary:
            bits.append(f"summary: {self.summary}")
        if self.output:
            bits.append(f"output:\n{self.output}")
        if self.question:
            bits.append(f"question: {self.question}")
        if self.error:
            bits.append(f"error: {self.error}")
        return "\n".join(bits)


def build_command(instruction: str, budget_usd: float | None = None) -> list[str]:
    """The spawn command of §4.9.1, exactly.

    `--permission-mode bypassPermissions` is not in the doc's version and has
    to be: in print mode a tool call that needs permission is denied, and a
    worker whose whole job is a file write would fail every time.
    """
    cmd = [
        "claude", "-p", instruction,
        "--output-format", "stream-json", "--verbose",
        "--system-prompt", cfg.SUBAGENT_PROMPT.read_text(),
        "--tools", cfg.SUBAGENT_TOOLS,
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--permission-mode", "bypassPermissions",
        "--effort", cfg.SUBAGENT_EFFORT,
    ]
    budget = cfg.SUBAGENT_BUDGET_USD if budget_usd is None else budget_usd
    if budget:
        cmd += ["--max-budget-usd", str(budget)]
    if cfg.MAIN_MODEL:
        cmd += ["--model", cfg.MAIN_MODEL]
    return cmd


def parse_final(text: str) -> dict | None:
    """The prompt requires the final message to be one JSON object. Parse it
    leniently — a fenced block or a trailing object still counts — but never
    guess a status: unparseable becomes `failed`, which is visible rather than
    silent (§ decision 2026-08-31)."""
    if not text:
        return None
    candidate = text.strip()
    if "```" in candidate:
        chunks = [c for c in candidate.split("```") if "{" in c]
        if chunks:
            candidate = chunks[-1].lstrip("json").strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(candidate[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and "status" in data else None


def run(instruction: str, subagent_id: str, trace_id: str | None = None,
        budget_usd: float | None = None, trace: Trace | None = None) -> SubagentResult:
    """Run one sub-agent to completion. Blocking — the runtime calls this on a
    worker thread, capped by a semaphore."""
    tr = trace or Trace()
    started = time.time()
    cfg.SUBAGENT_CWD.mkdir(parents=True, exist_ok=True)
    stderr_path = cfg.STDERR_DIR / f"{subagent_id}.stderr"
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    final_text, result_obj, last_assistant = "", None, ""
    try:
        with open(stderr_path, "w") as errf:
            proc = subprocess.Popen(
                build_command(instruction, budget_usd),
                cwd=str(cfg.SUBAGENT_CWD),        # clean cwd: no CLAUDE.md pickup
                stdin=subprocess.DEVNULL,          # `< /dev/null`: saves 3s per spawn
                stdout=subprocess.PIPE, stderr=errf, text=True,
            )
            assert proc.stdout is not None
            for line in proc.stdout:              # stream, so the trace is live
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tr.append("subagent_event", trace_id=trace_id,
                          subagent_id=subagent_id, line=event)
                if event.get("type") == "assistant":
                    text = " ".join(
                        c.get("text", "")
                        for c in (event.get("message") or {}).get("content", [])
                        if c.get("type") == "text")
                    if text.strip():
                        last_assistant = text
                if event.get("type") == "result":
                    result_obj = event
                    final_text = event.get("result") or ""
            proc.wait(timeout=cfg.SUBAGENT_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        return SubagentResult(subagent_id, "failed",
                              error=f"timed out after {cfg.SUBAGENT_TIMEOUT}s",
                              duration_sec=time.time() - started)
    except Exception as exc:
        return SubagentResult(subagent_id, "failed", error=f"spawn failed: {exc}",
                              duration_sec=time.time() - started)

    usage = (result_obj or {}).get("usage") or {}
    tokens = sum(int(usage.get(k) or 0) for k in
                 ("input_tokens", "cache_creation_input_tokens",
                  "cache_read_input_tokens", "output_tokens"))
    common = {
        "cost_usd": float((result_obj or {}).get("total_cost_usd") or 0.0),
        "tokens": tokens,
        "duration_sec": round(time.time() - started, 2),
    }

    if result_obj is None:
        return SubagentResult(subagent_id, "failed",
                              error="no result event — the worker died before finishing",
                              **common)
    if result_obj.get("is_error"):
        # Say what actually happened. `api_error_status` is null for most
        # failures; the useful fields are `subtype` and `terminal_reason`, and
        # stderr is usually empty because claude -p reports errors in-stream.
        detail = " · ".join(str(x) for x in (
            result_obj.get("subtype"), result_obj.get("terminal_reason"),
            result_obj.get("api_error_status"),
            f"spent ${common['cost_usd']:.2f}" if common["cost_usd"] else None,
            (stderr_path.read_text()[:400].strip() or None) if stderr_path.exists() else None,
        ) if x)
        # The worker may have finished and then tripped the cap on its way out
        # (measured: a completed write, reported as a failure, then redone by
        # the main agent at full cost). If it emitted a terminal status, that
        # status is the truth about the work; the error is context, not a verdict.
        salvaged = parse_final(final_text) or parse_final(last_assistant)
        if salvaged and salvaged.get("status") in ("done", "needs_input", "failed"):
            return SubagentResult(
                subagent_id, salvaged["status"],
                summary=str(salvaged.get("summary") or ""),
                output=str(salvaged.get("output") or ""),
                question=str(salvaged.get("question") or ""),
                error=f"[worker also ended abnormally: {detail}]",
                **common)
        return SubagentResult(subagent_id, "failed",
                              error=(detail or "claude -p reported an error")[:2000],
                              summary=last_assistant[:500], **common)

    parsed = parse_final(final_text) or parse_final(last_assistant)
    if parsed is None:
        return SubagentResult(
            subagent_id, "failed",
            error="worker did not return the required JSON object",
            summary=(final_text or last_assistant)[:1000], **common)

    status = parsed.get("status")
    if status not in ("done", "needs_input", "failed"):
        return SubagentResult(subagent_id, "failed",
                              error=f"unknown terminal status: {status!r}",
                              summary=final_text[:1000], **common)

    return SubagentResult(
        subagent_id, status,
        summary=str(parsed.get("summary") or ""),
        output=str(parsed.get("output") or ""),
        question=str(parsed.get("question") or ""),
        error=str(parsed.get("error") or ""),
        **common,
    )
