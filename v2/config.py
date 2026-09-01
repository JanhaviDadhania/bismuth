"""Paths and settings for v2. One place, no adapter layer (§1).

Nothing here is a swappable backend. Telegram is Telegram, faster-whisper is
faster-whisper, `claude -p` is `claude -p`. These are knobs, not seams.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import BASE_DIR, MEMORY_DIR, load_config  # noqa: E402

_cfg = load_config()
_v2 = _cfg.get("v2") or {}
_env = _cfg.get("env") or {}

# Test/scratch override. Set both to point a whole v2 at a throwaway tree —
# used by the test suite, and by `python3 -m v2.smoke`, so nothing rehearses
# against her real memory.
if os.environ.get("BISMUTH2_MEMORY_DIR"):
    MEMORY_DIR = Path(os.path.expanduser(os.environ["BISMUTH2_MEMORY_DIR"])).resolve()


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(str(p)))


# ─── Runtime state (tier 1 + tier 2 caches) — §6 ─────────────────────────────

RUNTIME_DIR = _expand(
    os.environ.get("BISMUTH2_RUNTIME_DIR") or _v2.get("runtime_dir", "~/.bismuth")
)
STATE_FILE = RUNTIME_DIR / "state.json"
STATE_TMP = RUNTIME_DIR / ".state.json.tmp"
STATE_LOCK = RUNTIME_DIR / ".state.lock"
SPOOL_DIR = RUNTIME_DIR / "spool"            # raw Telegram updates, durable
STAGING_DIR = RUNTIME_DIR / "staging"        # downloaded media, pre-archive
TASKS_CACHE = RUNTIME_DIR / "tasks.json"     # tier 2 — derived, deletable
SUBAGENTS_CACHE = RUNTIME_DIR / "subagents.json"
PID_FILE = RUNTIME_DIR / "bismuth2.pid"
STDERR_DIR = RUNTIME_DIR / "agent_stderr"

# ─── Memory and the record ───────────────────────────────────────────────────

TRACE_DIR = MEMORY_DIR / "trace"             # log-YYYY-MM.jsonl, never rotated
TRACE_LOCK = RUNTIME_DIR / ".trace.lock"
TRACE_SEQ_FILE = RUNTIME_DIR / "trace_seq"
OTHERS_DIR = MEMORY_DIR / "others"           # the parking folder — §4.7

# Reserved, machine-owned folders. `_`-prefixed, and therefore invisible to
# DESTINATIONS by the generic rule in `destinations.py` — an ordinary note can
# never be routed into one. That matters: if `_schedules/` were routable, the
# main agent could file a grocery list into it and `tick()` would try to parse
# the grocery list as a schedule.
SCHEDULES_DIR = MEMORY_DIR / "_schedules"    # WHEN — a clock, one turn each
TOOLS_DIR = MEMORY_DIR / "_tools"            # WHAT WITH — a card a worker reads
AUDIO_REPO = _expand(_v2.get("audio_repo", "~/bismuth-audio"))

# ─── Prompts — the only behavioural content in the system ────────────────────

PROMPTS_DIR = BASE_DIR / "prompts" / "v2"
MAIN_AGENT_PROMPT = PROMPTS_DIR / "main_agent.md"
SUBAGENT_PROMPT = PROMPTS_DIR / "subagent.md"
INTENT_SCHEMA = PROMPTS_DIR / "intent_schema.json"

# ─── Telegram ────────────────────────────────────────────────────────────────
# v2 must be built against a SECOND bot token (§11): v1 and v2 cannot both
# long-poll getUpdates on one token without stealing each other's messages.

TELEGRAM_TOKEN = (
    os.environ.get("BISMUTH2_TELEGRAM_BOT_TOKEN")
    or _v2.get("telegram_bot_token")
    or ""
)
TELEGRAM_CHAT_ID = str(
    os.environ.get("BISMUTH2_TELEGRAM_CHAT_ID")
    or _v2.get("telegram_chat_id")
    or _env.get("TELEGRAM_CHAT_ID")
    or ""
)
POLL_TIMEOUT = int(_v2.get("poll_timeout", 25))          # long-poll seconds
TELEGRAM_MSG_LIMIT = 4000                                 # split above this

# ─── The main agent — §4.5 ───────────────────────────────────────────────────

MAIN_MODEL = _v2.get("main_model") or None                # None = CLI default
CONTEXT_WINDOW = int(_v2.get("context_window", 200_000))
RESET_PCT = float(_v2.get("reset_pct", 0.40))             # hard reset at 40%
MAIN_AGENT_TIMEOUT = int(_v2.get("main_agent_timeout", 600))
DONE_TAIL = int(_v2.get("done_tail", 5))                  # §4.8 concession
ACK_TAIL = int(_v2.get("ack_tail", 10))                   # board strip

# ─── Sub-agents — §4.9.1 ─────────────────────────────────────────────────────

SUBAGENT_TOOLS = "Read,Write,Edit,Bash"
SUBAGENT_EFFORT = _v2.get("subagent_effort", "low")       # never thinking-off
# A blast-radius bound, not a cost target. 0.50 was too tight in practice: a
# legitimate multi-file write hit the cap *after* finishing, and the work was
# then reported as failed and redone at full cost.
SUBAGENT_BUDGET_USD = float(_v2.get("subagent_budget_usd", 2.00))
SUBAGENT_TIMEOUT = int(_v2.get("subagent_timeout", 900))
MAX_CONCURRENT_SUBAGENTS = int(_v2.get("max_concurrent_subagents", 3))
SUBAGENT_CWD = _expand(_v2.get("subagent_cwd", "~/.bismuth/workdir"))

# ─── STT — §4.4 ──────────────────────────────────────────────────────────────

TRANSCRIBE_SCRIPT = BASE_DIR / "tools" / "transcribe.py"
TRANSCRIBE_TIMEOUT = int(_v2.get("transcribe_timeout", 300))
WHISPER_MODEL = _v2.get("whisper_model", "base")

# ─── Trace hygiene — §5 ──────────────────────────────────────────────────────
# No rotation, ever. The per-event size cap is the only thing bounding growth,
# so it is not optional: one tool result can be an entire file read.

TRACE_EVENT_CAP = int(_v2.get("trace_event_cap", 8_000))  # chars per field

# ─── Background loops ───────────────────────────────────────────────────────

AUDIO_PUSH_INTERVAL = int(_v2.get("audio_push_interval", 900))
MEMORY_SYNC_INTERVAL = int(_v2.get("memory_sync_interval", 300))
BOARD_REFRESH_INTERVAL = int(_v2.get("board_refresh_interval", 120))
# The background loop sleeps 5s, so this gate is what sets the real schedule
# granularity: ~1 minute. Finer would buy nothing — `at:` is a wall-clock
# minute, and firing is deliberately late-tolerant.
SCHEDULE_TICK_INTERVAL = int(_v2.get("schedule_tick_interval", 60))
# How long after firing before a missing `produces:` artifact is reported. A
# knob and not a constant so a scratch tree can set it to 0 and exercise the
# verification path without waiting two hours.
SCHEDULE_OVERDUE_AFTER = int(_v2.get("schedule_overdue_after", 2 * 3600))

DIRS_TO_CREATE = (
    RUNTIME_DIR, SPOOL_DIR, STAGING_DIR, STDERR_DIR, TRACE_DIR, OTHERS_DIR,
    SUBAGENT_CWD, SCHEDULES_DIR, TOOLS_DIR,
)


def ensure_dirs() -> None:
    for d in DIRS_TO_CREATE:
        d.mkdir(parents=True, exist_ok=True)


def check() -> list[str]:
    """Startup preflight. Returns a list of problems, empty if all is well."""
    problems: list[str] = []
    if not TELEGRAM_TOKEN:
        problems.append(
            "no Telegram token: set v2.telegram_bot_token in config.yaml or "
            "BISMUTH2_TELEGRAM_BOT_TOKEN."
        )
    if not TELEGRAM_CHAT_ID:
        problems.append("no TELEGRAM_CHAT_ID configured")
    for p in (MAIN_AGENT_PROMPT, SUBAGENT_PROMPT, INTENT_SCHEMA):
        if not p.exists():
            problems.append(f"missing prompt file: {p}")
    if not MEMORY_DIR.exists():
        problems.append(f"memory dir does not exist: {MEMORY_DIR}")
    return problems
