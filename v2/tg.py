"""Telegram — the transport, in and out (§4.1, §4.10).

One bot, one channel, and only the main agent is ever on it. Nothing else in
the runtime is allowed to send content here: one voice (§1).
"""

from __future__ import annotations

import time
from pathlib import Path

import requests

from . import config as cfg

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(RuntimeError):
    pass


def _url(method: str) -> str:
    return API.format(token=cfg.TELEGRAM_TOKEN, method=method)


def get_updates(offset: int, timeout: int | None = None) -> tuple[list[dict], int]:
    """One long-poll. Returns (updates, next_offset).

    The caller must spool the updates durably BEFORE persisting next_offset —
    the offset is the commit point (§4.2).
    """
    timeout = cfg.POLL_TIMEOUT if timeout is None else timeout
    resp = requests.get(
        _url("getUpdates"),
        params={"offset": offset, "timeout": timeout},
        timeout=timeout + 15,
    )
    data = resp.json()
    if not data.get("ok"):
        raise TelegramError(data.get("description", "getUpdates not ok"))
    updates = data.get("result") or []
    next_offset = updates[-1]["update_id"] + 1 if updates else offset
    return updates, next_offset


def get_file_url(file_id: str) -> str:
    resp = requests.get(_url("getFile"), params={"file_id": file_id}, timeout=30)
    data = resp.json()
    if not data.get("ok"):
        raise TelegramError(data.get("description", "getFile not ok"))
    return f"https://api.telegram.org/file/bot{cfg.TELEGRAM_TOKEN}/{data['result']['file_path']}"


def download(file_id: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(get_file_url(file_id), timeout=120)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def _post(method: str, data: dict, files: dict | None = None) -> dict:
    resp = requests.post(_url(method), data=data, files=files, timeout=60)
    payload = resp.json()
    if not payload.get("ok"):
        raise TelegramError(payload.get("description", f"{method} not ok"))
    return payload["result"]


def send_message(text: str) -> list[int]:
    """Send text, splitting on Telegram's 4096-char limit. Returns message ids.

    Splitting is on paragraph then line boundaries so a long reply does not get
    cut mid-word — though the prompt tells the agent not to send 200–300 lines
    in the first place (§4.10)."""
    ids = []
    for chunk in _split(text, cfg.TELEGRAM_MSG_LIMIT):
        result = _post("sendMessage", {"chat_id": cfg.TELEGRAM_CHAT_ID, "text": chunk})
        ids.append(result["message_id"])
        if len(ids) > 1:
            time.sleep(0.3)          # stay under Telegram's per-chat rate limit
    return ids


def send_voice(ogg_path: Path, caption: str = "") -> int:
    with open(ogg_path, "rb") as f:
        result = _post("sendVoice",
                       {"chat_id": cfg.TELEGRAM_CHAT_ID, "caption": caption[:1000]},
                       files={"voice": f})
    return result["message_id"]


def send_document(path: Path, caption: str = "") -> int:
    with open(path, "rb") as f:
        result = _post("sendDocument",
                       {"chat_id": cfg.TELEGRAM_CHAT_ID, "caption": caption[:1000]},
                       files={"document": f})
    return result["message_id"]


def _split(text: str, limit: int) -> list[str]:
    text = text or ""
    if len(text) <= limit:
        return [text] if text else []
    chunks, current = [], ""
    for para in text.split("\n\n"):
        candidate = (current + "\n\n" + para) if current else para
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(para) > limit:
            cut = para.rfind("\n", 0, limit)
            cut = cut if cut > limit // 2 else limit
            chunks.append(para[:cut])
            para = para[cut:].lstrip("\n")
        current = para
    if current:
        chunks.append(current)
    return chunks
