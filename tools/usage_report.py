#!/usr/bin/env python3
"""Usage report — aggregates bismuth's python-owned logs into a weekly HTML report.

Reads:
  projects/bismuth/usage_log.jsonl    (one summary line per agent turn / executor run)
  projects/bismuth/transcripts/*.jsonl (stream-json events; only tool_use heads are read)

Writes a standalone HTML file with, per ISO week: turns, tokens, cost, and
tool-call counts per tool.

Usage:
  python3 tools/usage_report.py [--out /path/report.html]
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MEMORY_DIR

USAGE_LOG = MEMORY_DIR / "projects" / "bismuth" / "usage_log.jsonl"
TRANSCRIPTS_DIR = MEMORY_DIR / "projects" / "bismuth" / "transcripts"
DEFAULT_OUT = MEMORY_DIR / "projects" / "bismuth" / "usage_report.html"


def _week(ts: str) -> str:
    year, week, _ = datetime.fromisoformat(ts).isocalendar()
    return f"{year}-W{week:02d}"


def _iter_jsonl(path: Path):
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def collect(usage_log: Path = USAGE_LOG,
            transcripts_dir: Path = TRANSCRIPTS_DIR) -> dict:
    """Aggregate both logs into {week: {turns, tokens, cost, tools{name: count}}}."""
    weeks: dict = defaultdict(lambda: {
        "turns": 0, "input_tokens": 0, "output_tokens": 0,
        "cache_read": 0, "cache_write": 0, "cost_usd": 0.0,
        "tools": defaultdict(int),
    })
    for e in _iter_jsonl(usage_log):
        ts = e.get("ts")
        if not ts:
            continue
        w = weeks[_week(ts)]
        w["turns"] += 1
        w["cost_usd"] += e.get("total_cost_usd") or 0.0
        u = e.get("usage") or {}
        w["input_tokens"] += u.get("input_tokens") or 0
        w["output_tokens"] += u.get("output_tokens") or 0
        w["cache_read"] += u.get("cache_read_input_tokens") or 0
        w["cache_write"] += u.get("cache_creation_input_tokens") or 0
    if transcripts_dir.is_dir():
        for path in sorted(transcripts_dir.glob("*.jsonl")):
            for e in _iter_jsonl(path):
                ev = e.get("event") or {}
                if ev.get("type") != "assistant" or "ts" not in e:
                    continue
                for block in (ev.get("message") or {}).get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        weeks[_week(e["ts"])]["tools"][block.get("name", "?")] += 1
    return dict(sorted(weeks.items()))


def _fmt(n: float) -> str:
    return f"{n:,}" if isinstance(n, int) else f"{n:,.2f}"


def render_html(weeks: dict) -> str:
    week_names = list(weeks)
    totals = {k: sum(w[k] for w in weeks.values())
              for k in ("turns", "input_tokens", "output_tokens",
                        "cache_read", "cache_write", "cost_usd")}
    tool_totals: dict = defaultdict(int)
    for w in weeks.values():
        for name, n in w["tools"].items():
            tool_totals[name] += n
    tools_sorted = sorted(tool_totals, key=tool_totals.get, reverse=True)

    def table(headers, rows):
        head = "".join(f"<th>{h}</th>" for h in headers)
        body = "".join(
            "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    weekly_rows = [
        [wk, _fmt(w["turns"]), _fmt(w["input_tokens"]), _fmt(w["output_tokens"]),
         _fmt(w["cache_read"]), _fmt(w["cache_write"]), f"${w['cost_usd']:,.2f}"]
        for wk, w in weeks.items()]
    tool_rows = [
        [name] + [_fmt(weeks[wk]["tools"].get(name, 0)) for wk in week_names]
        + [_fmt(tool_totals[name])]
        for name in tools_sorted]

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>bismuth usage</title>
<style>
  body {{ font-family: -apple-system, sans-serif; margin: 2rem auto; max-width: 60rem; color: #222; }}
  h1 {{ font-size: 1.4rem; }} h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: .5rem; }}
  th, td {{ border: 1px solid #ddd; padding: .4rem .6rem; text-align: right; font-size: .9rem; }}
  th:first-child, td:first-child {{ text-align: left; }}
  thead {{ background: #f5f5f5; }}
  .totals span {{ display: inline-block; margin-right: 1.5rem; }}
  .totals b {{ font-size: 1.2rem; }}
</style></head><body>
<h1>bismuth usage report</h1>
<p>generated {datetime.now():%Y-%m-%d %H:%M}</p>
<p class="totals">
  <span><b>{_fmt(totals["turns"])}</b> turns</span>
  <span><b>{_fmt(totals["input_tokens"])}</b> input tok</span>
  <span><b>{_fmt(totals["output_tokens"])}</b> output tok</span>
  <span><b>{_fmt(totals["cache_read"])}</b> cache read</span>
  <span><b>${totals["cost_usd"]:,.2f}</b> total cost</span>
</p>
<h2>by week</h2>
{table(["week", "turns", "input", "output", "cache read", "cache write", "cost"], weekly_rows)}
<h2>tool calls</h2>
{table(["tool"] + week_names + ["total"], tool_rows)
 if tool_rows else "<p>no transcript data yet — tool counts appear after the transcripts log starts filling.</p>"}
</body></html>
"""


def usage_report(usage_log: Path = USAGE_LOG,
                 transcripts_dir: Path = TRANSCRIPTS_DIR,
                 out: Path = DEFAULT_OUT) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(collect(usage_log, transcripts_dir)))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--usage-log", type=Path, default=USAGE_LOG)
    ap.add_argument("--transcripts-dir", type=Path, default=TRANSCRIPTS_DIR)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    print(usage_report(args.usage_log, args.transcripts_dir, args.out))
