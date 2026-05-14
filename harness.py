"""
Bismuth v2 harness — always-on message router and agent orchestrator.

Owns:
  - Telegram long-polling
  - Agent invocation (assistant ↔ coffeechat)
  - Executor lifecycle (spawn, monitor, reap)
  - Exit-token parsing
  - State persistence (memory/.harness/state.json)
  - Calendar polling stub (1-hour timer; calendar tool TBD)

Design doc: HARNESS_DESIGN.md
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import BASE_DIR, MEMORY_DIR, load_config


# ─── Paths ───────────────────────────────────────────────────────────────────

HARNESS_DIR = MEMORY_DIR / ".harness"
STATE_FILE = HARNESS_DIR / "state.json"
STATE_BACKUP = HARNESS_DIR / ".state.json.bak"
STATE_TMP = HARNESS_DIR / ".state.json.tmp"
LOG_FILE = HARNESS_DIR / "log.jsonl"
PENDING_TASKS_DIR = HARNESS_DIR / "pending_tasks"


# ─── Tunables ────────────────────────────────────────────────────────────────

EXECUTOR_CAP = 3
LONG_POLL_TIMEOUT = 50      # seconds — Telegram thread holds the connection this long
MAIN_TICK = 1.0             # seconds — main loop max idle wait between mailbox/buffer checks
AGENT_TIMEOUT = 600
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


# ─── Environment ─────────────────────────────────────────────────────────────

def _load_env():
    env = load_config().get("env", {})
    for key, value in env.items():
        if value:
            os.environ.setdefault(key, str(value))


def _tg_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise EnvironmentError("TELEGRAM_BOT_TOKEN not set")
    return token


def _tg_chat_id() -> str:
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise EnvironmentError("TELEGRAM_CHAT_ID not set")
    return chat_id


# ─── State ───────────────────────────────────────────────────────────────────

def default_state() -> dict:
    return {
        "active_agent": "assistant",
        "telegram_offset": 0,
        "executors": {},
        "pending_buffer": [],
    }


def init_dirs():
    HARNESS_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_TASKS_DIR.mkdir(parents=True, exist_ok=True)


def read_state() -> dict:
    for path in (STATE_FILE, STATE_BACKUP):
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            log_event("state_corrupt", path=str(path))
    return default_state()


def write_state(state: dict):
    STATE_TMP.write_text(json.dumps(state, indent=2, sort_keys=True))
    with open(STATE_TMP, "rb+") as f:
        os.fsync(f.fileno())
    if STATE_FILE.exists():
        os.replace(STATE_FILE, STATE_BACKUP)
    os.replace(STATE_TMP, STATE_FILE)


# ─── Logging ─────────────────────────────────────────────────────────────────

def log_event(event_type: str, **kwargs):
    entry = {"ts": datetime.now().isoformat(), "type": event_type, **kwargs}
    try:
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
    print(f"[harness] {event_type} {kwargs}", flush=True)


# ─── Telegram ────────────────────────────────────────────────────────────────

def _fetch_telegram(offset: int, timeout: int) -> tuple[list[str], int]:
    """One getUpdates call. Returns (text messages, new offset)."""
    url = TELEGRAM_API.format(token=_tg_token(), method="getUpdates")
    try:
        resp = requests.get(
            url,
            params={"offset": offset, "timeout": timeout},
            timeout=timeout + 10,
        )
        data = resp.json()
        if not data.get("ok"):
            return [], offset
        updates = data.get("result", [])
        if not updates:
            return [], offset
        new_offset = updates[-1]["update_id"] + 1
        texts = []
        for u in updates:
            msg = u.get("message") or u.get("edited_message")
            if not msg:
                continue
            if "text" in msg:
                texts.append(msg["text"])
            elif "caption" in msg:
                texts.append(msg["caption"])
        return texts, new_offset
    except Exception as e:
        log_event("telegram_error", error=str(e))
        return [], offset


def telegram_send(text: str):
    url = TELEGRAM_API.format(token=_tg_token(), method="sendMessage")
    try:
        requests.post(url, data={"chat_id": _tg_chat_id(), "text": text}, timeout=15)
    except Exception as e:
        log_event("telegram_send_error", error=str(e))


# ─── Telegram background thread ──────────────────────────────────────────────

class TelegramPoller(threading.Thread):
    """
    Background thread that long-polls Telegram and deposits messages into a
    shared inbox. Wakes the main loop via tg_event so the new agent runs
    immediately instead of waiting for the next long-poll cycle to expire.
    """

    def __init__(self, initial_offset: int):
        super().__init__(daemon=True, name="telegram-poller")
        self.offset = initial_offset
        self.inbox: list[str] = []
        self.lock = threading.Lock()
        self.event = threading.Event()
        self.shutdown = threading.Event()

    def run(self):
        while not self.shutdown.is_set():
            with self.lock:
                offset = self.offset
            messages, new_offset = _fetch_telegram(offset, LONG_POLL_TIMEOUT)
            with self.lock:
                self.offset = new_offset
                if messages:
                    self.inbox.extend(messages)
            if messages:
                self.event.set()

    def drain(self) -> tuple[list[str], int]:
        """Atomically take all queued messages + current offset."""
        with self.lock:
            messages = self.inbox[:]
            self.inbox.clear()
            return messages, self.offset

    def stop(self):
        self.shutdown.set()


# ─── Mailbox ─────────────────────────────────────────────────────────────────

def read_mailbox(state: dict) -> list[str]:
    """Collect synthetic messages from executor scratch dirs."""
    synthetic = []
    for uid, info in list(state.get("executors", {}).items()):
        exec_dir = HARNESS_DIR / f"executor_{uid}"
        status_file = exec_dir / "status"
        if not status_file.exists():
            continue
        status = status_file.read_text().strip()
        short = uid[:8]
        project = info.get("project", "general")

        if status == "asking":
            q = exec_dir / "question.txt"
            ans = exec_dir / "answer.txt"
            if q.exists() and not ans.exists() and not info.get("question_relayed"):
                question = q.read_text().strip()
                synthetic.append(
                    f"[executor #{short} for {project}]: {question}\n"
                    f"To answer, write your reply to: {ans}"
                )
                info["question_relayed"] = True

        elif status == "done" and not info.get("result_relayed"):
            summary_file = exec_dir / "result_summary.txt"
            summary = summary_file.read_text().strip() if summary_file.exists() else "(no summary)"
            synthetic.append(f"[executor #{short} for {project}]: DONE — {summary}")
            info["result_relayed"] = True
            info["status"] = "done"

        elif status == "failed" and not info.get("result_relayed"):
            synthetic.append(f"[executor #{short} for {project}]: FAILED — check {exec_dir}/stderr.log")
            info["result_relayed"] = True
            info["status"] = "failed"

    return synthetic


# ─── Agent invocation ────────────────────────────────────────────────────────

def _substitute(text: str, project: str = "general") -> str:
    return (text
            .replace("{MEMORY_DIR}", str(MEMORY_DIR))
            .replace("{HARNESS_DIR}", str(HARNESS_DIR))
            .replace("{PENDING_TASKS_DIR}", str(PENDING_TASKS_DIR))
            .replace("{TELEGRAM_CLI}", str(BASE_DIR / "tools" / "telegram_cli.py"))
            .replace("{project_name}", project)
            .replace("{PROJECT}", project))


def build_prompt(agent_name: str) -> str:
    prompts_dir = BASE_DIR / "prompts"
    if agent_name == "assistant":
        return _substitute((prompts_dir / "assistant.md").read_text())
    if agent_name.startswith("coffeechat:"):
        project = agent_name.split(":", 1)[1]
        return _substitute((prompts_dir / "coffeechat.md").read_text(), project=project)
    raise ValueError(f"unknown agent: {agent_name}")


def run_agent(agent_name: str, batch: list[str]) -> tuple[str, int]:
    system = build_prompt(agent_name)
    user_msg = "Incoming batch (in order received):\n" + "\n".join(
        f"{i+1}. {m}" for i, m in enumerate(batch)
    )
    log_event("agent_start", agent=agent_name, batch_size=len(batch))
    try:
        result = subprocess.run(
            ["claude", "-p", user_msg,
             "--system-prompt", system,
             "--dangerously-skip-permissions"],
            cwd=str(BASE_DIR),
            capture_output=True, text=True,
            timeout=AGENT_TIMEOUT,
        )
        log_event("agent_done", agent=agent_name, exit_code=result.returncode)
        return result.stdout, result.returncode
    except subprocess.TimeoutExpired:
        log_event("agent_timeout", agent=agent_name)
        return "", -1


# ─── Exit token parsing ──────────────────────────────────────────────────────

TOKEN_PATTERNS = {
    "SWITCH":          re.compile(r"^SWITCH:(.+)$", re.MULTILINE),
    "SPAWN_EXECUTOR":  re.compile(r"^SPAWN_EXECUTOR:(.+)$", re.MULTILINE),
    "PENDING":         re.compile(r"^PENDING:(.+)$", re.MULTILINE),
    "HALT":            re.compile(r"^HALT\s*$", re.MULTILINE),
}


def parse_tokens(stdout: str) -> dict:
    tokens = {}
    for name, pattern in TOKEN_PATTERNS.items():
        m = pattern.search(stdout)
        if m:
            tokens[name] = m.group(1).strip() if m.groups() else True
    return tokens


# ─── Executors ───────────────────────────────────────────────────────────────

def running_count(state: dict) -> int:
    return sum(1 for e in state["executors"].values() if e.get("status") == "running")


def spawn_executor(task_id: str, project: str, state: dict) -> bool:
    pending = PENDING_TASKS_DIR / f"{task_id}.md"
    if not pending.exists():
        log_event("spawn_failed_no_task", task_id=task_id)
        return False

    if running_count(state) >= EXECUTOR_CAP:
        log_event("executor_at_cap", task_id=task_id)
        telegram_send(f"executor cap ({EXECUTOR_CAP}) reached; task {task_id} queued — re-spawn later")
        return False

    uid = uuid.uuid4().hex
    exec_dir = HARNESS_DIR / f"executor_{uid}"
    exec_dir.mkdir(parents=True, exist_ok=True)
    (exec_dir / "task.md").write_text(pending.read_text())
    (exec_dir / "status").write_text("running")
    pending.unlink()

    template = (BASE_DIR / "prompts" / "executor.md").read_text()
    system = (template
              .replace("{MEMORY_DIR}", str(MEMORY_DIR))
              .replace("{EXEC_DIR}", str(exec_dir))
              .replace("{PROJECT}", project))

    user_msg = f"Your task is in {exec_dir / 'task.md'}. Read it and begin."

    stdout_log = open(exec_dir / "stdout.log", "w")
    stderr_log = open(exec_dir / "stderr.log", "w")
    proc = subprocess.Popen(
        ["claude", "-p", user_msg,
         "--system-prompt", system,
         "--dangerously-skip-permissions"],
        cwd=str(BASE_DIR),
        stdout=stdout_log,
        stderr=stderr_log,
    )
    state["executors"][uid] = {
        "pid": proc.pid,
        "project": project,
        "task_id": task_id,
        "started_at": datetime.now().isoformat(),
        "status": "running",
    }
    log_event("executor_spawned", uuid=uid, pid=proc.pid, project=project, task_id=task_id)
    return True


def reap_executors(state: dict):
    """Reconcile on-disk status with process state."""
    for uid, info in list(state["executors"].items()):
        exec_dir = HARNESS_DIR / f"executor_{uid}"
        status_file = exec_dir / "status"
        on_disk = status_file.read_text().strip() if status_file.exists() else None

        # Promote disk status to state
        if on_disk in ("done", "failed", "asking"):
            info["status"] = on_disk
            continue

        # If process is gone but disk still says running → mark failed
        try:
            os.kill(info["pid"], 0)
        except (ProcessLookupError, PermissionError):
            if info["status"] == "running":
                info["status"] = "failed"
                if status_file.exists():
                    status_file.write_text("failed")
                log_event("executor_died", uuid=uid)


def halt_all(state: dict):
    for uid, info in state["executors"].items():
        if info.get("status") == "running":
            try:
                os.kill(info["pid"], 9)
            except ProcessLookupError:
                pass
            info["status"] = "failed"
            log_event("executor_killed", uuid=uid, reason="HALT")


# ─── Token handling ──────────────────────────────────────────────────────────

def handle_tokens(tokens: dict, state: dict):
    if "HALT" in tokens:
        halt_all(state)
        state["pending_buffer"] = []
        state["active_agent"] = "assistant"
        telegram_send("HALT — all executors stopped, back to assistant.")
        log_event("halt")

    if "PENDING" in tokens:
        try:
            buf = json.loads(tokens["PENDING"])
            if isinstance(buf, list):
                state["pending_buffer"] = buf
        except json.JSONDecodeError:
            log_event("pending_parse_error", raw=tokens["PENDING"])

    if "SPAWN_EXECUTOR" in tokens:
        payload = tokens["SPAWN_EXECUTOR"]
        if ":" in payload:
            task_id, project = payload.split(":", 1)
        else:
            task_id, project = payload, "general"
        spawn_executor(task_id.strip(), project.strip(), state)

    if "SWITCH" in tokens:
        spec = tokens["SWITCH"]
        if spec == "assistant" or spec.startswith("coffeechat:"):
            state["active_agent"] = spec
            log_event("switch", to=spec)
        else:
            log_event("unknown_switch", spec=spec)


# ─── Main loop ───────────────────────────────────────────────────────────────

def main():
    _load_env()
    init_dirs()
    state = read_state()
    log_event("harness_start", active_agent=state["active_agent"])

    poller = TelegramPoller(initial_offset=state["telegram_offset"])
    poller.start()

    try:
        while True:
            try:
                # Wait for *any* wake source: telegram message or MAIN_TICK timeout.
                # Timeout still lets us periodically check mailbox + pending buffer
                # even when no telegram message arrives.
                poller.event.wait(timeout=MAIN_TICK)
                poller.event.clear()

                messages, current_offset = poller.drain()
                state["telegram_offset"] = current_offset

                reap_executors(state)
                synthetic = read_mailbox(state)

                buffer = state.get("pending_buffer", [])
                batch = buffer + synthetic + messages
                state["pending_buffer"] = []

                if not batch:
                    write_state(state)
                    continue

                stdout, _ = run_agent(state["active_agent"], batch)
                tokens = parse_tokens(stdout)
                handle_tokens(tokens, state)

                write_state(state)

            except KeyboardInterrupt:
                raise
            except Exception as e:
                log_event("loop_error", error=str(e))
                time.sleep(5)
    except KeyboardInterrupt:
        log_event("harness_stop", reason="keyboard")
        print("\nHarness stopped.")
        poller.stop()


if __name__ == "__main__":
    main()
