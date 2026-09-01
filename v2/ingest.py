"""Ingest — §4.2. Telegram in, durably, with the offset as the commit point.

The failure this must not repeat: v1 ran on this path and lost messages —
`dead_letter/` holds 113 entries, 15 of them real, including "can you hear
me?" from 13 June, and nothing ever told her. So: spool to disk before the
offset moves, dedup on update_id, and **nothing is ever silently dropped**.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from . import config as cfg
from . import archive, state, tg
from .trace import Trace

MEDIA_KINDS = ("voice", "audio", "photo", "video", "document")


def spool_path(update_id: int) -> Path:
    return cfg.SPOOL_DIR / f"{update_id:012d}.json"


def spool(update: dict) -> Path:
    """Durable before the offset moves. fsync, then rename — a crash between
    the two means Telegram serves the message again, which dedup absorbs."""
    cfg.SPOOL_DIR.mkdir(parents=True, exist_ok=True)
    path = spool_path(update["update_id"])
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(update, f)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)
    return path


def spooled() -> list[Path]:
    if not cfg.SPOOL_DIR.exists():
        return []
    return sorted(cfg.SPOOL_DIR.glob("*.json"))


class Poller(threading.Thread):
    """Long-polls getUpdates. Does nothing else: download, transcription and
    routing all happen downstream, so a slow whisper run can never stall the
    thing that is keeping messages from being lost."""

    def __init__(self, trace: Trace, on_message=None):
        super().__init__(daemon=True, name="tg-poller")
        self.trace = trace
        self.on_message = on_message
        self._stop = threading.Event()
        self.last_error: str | None = None

    def run(self) -> None:
        backoff = 1
        while not self._stop.is_set():
            try:
                offset = state.read().get("offset", 0)
                updates, next_offset = tg.get_updates(offset)
                for update in updates:
                    self._accept(update)
                if next_offset != offset:
                    with state.mutate() as s:      # offset moves LAST
                        s["offset"] = next_offset
                if self.on_message and updates:
                    self.on_message()
                backoff = 1
                self.last_error = None
            except Exception as exc:
                self.last_error = str(exc)
                self.trace.append("telegram_error", error=str(exc)[:500])
                self._stop.wait(min(backoff, 60))
                backoff = min(backoff * 2, 60)

    def _accept(self, update: dict) -> None:
        update_id = update.get("update_id")
        msg = update.get("message") or update.get("edited_message") or {}
        spool(update)
        kind = next((k for k in MEDIA_KINDS if k in msg), "text" if "text" in msg else "other")
        self.trace.append("note_received", trace_id=f"upd_{update_id}",
                          update_id=update_id,
                          telegram_date=msg.get("date"),
                          bytes=len(json.dumps(update)),
                          kind=kind)

    def stop(self) -> None:
        self._stop.set()


def transcribe(path: Path, trace: Trace, trace_id: str) -> str | None:
    """faster-whisper in a subprocess, so the model never lives in this
    process: memory is freed after each use and a model download cannot wedge
    the runtime (§4.4)."""
    import subprocess
    started = time.time()
    try:
        proc = subprocess.run(
            ["python3", str(cfg.TRANSCRIBE_SCRIPT), str(path),
             "--model-size", cfg.WHISPER_MODEL],
            capture_output=True, text=True, timeout=cfg.TRANSCRIBE_TIMEOUT)
        data = json.loads(proc.stdout or "{}")
    except Exception as exc:
        trace.append("stt_failed", trace_id=trace_id, error=str(exc)[:400])
        return None
    if not data.get("success"):
        trace.append("stt_failed", trace_id=trace_id, error=data.get("error"))
        return None
    transcript = (data.get("transcript") or "").strip()
    trace.append("stt_done", trace_id=trace_id, transcript=transcript,
                 model=cfg.WHISPER_MODEL,
                 duration_sec=round(time.time() - started, 2))
    return transcript


def prepare(update: dict, trace: Trace) -> dict | None:
    """One spooled update → one turn-queue item, or None if it carries nothing
    the agent can act on. Media is downloaded, audio is archived, voice is
    transcribed — all after the message is already safe on disk."""
    update_id = update.get("update_id")
    trace_id = f"upd_{update_id}"
    msg = update.get("message") or update.get("edited_message") or {}
    edited = "edited_message" in update
    item = {"kind": "note", "trace_id": trace_id, "update_id": update_id,
            "voice": False, "text": ""}

    if "text" in msg:
        item["text"] = ("[edited] " if edited else "") + msg["text"]
        return item

    if "voice" in msg or "audio" in msg:
        node = msg.get("voice") or msg["audio"]
        suffix = ".ogg" if "voice" in msg else ".mp3"
        staged = cfg.STAGING_DIR / f"{trace_id}{suffix}"
        try:
            tg.download(node["file_id"], staged)
        except Exception as exc:
            trace.append("media_download_failed", trace_id=trace_id, error=str(exc)[:300])
            item["text"] = "[voice note — download failed; tell her you could not hear it]"
            return item
        transcript = transcribe(staged, trace, trace_id)
        archive.archive(staged, trace_id, trace)          # off the critical path
        caption = (msg.get("caption") or "").strip()
        if transcript:
            item["text"] = transcript + (f"\n[caption: {caption}]" if caption else "")
            item["voice"] = True
        else:
            item["text"] = ("[voice note — transcription failed. The audio is "
                            "archived. Park this and tell her.]"
                            + (f"\n[caption: {caption}]" if caption else ""))
        return item

    for kind in ("photo", "video", "document"):
        if kind in msg:
            node = msg[kind][-1] if kind == "photo" else msg[kind]
            name = node.get("file_name") or f"{trace_id}_{kind}"
            staged = cfg.STAGING_DIR / f"{trace_id}__{name}"
            try:
                tg.download(node["file_id"], staged)
                where = str(staged)
            except Exception as exc:
                trace.append("media_download_failed", trace_id=trace_id, error=str(exc)[:300])
                where = "download failed"
            caption = (msg.get("caption") or "").strip()
            item["text"] = f"[{kind} from her — saved at {where}]" + (
                f"\ncaption: {caption}" if caption else "")
            return item

    trace.append("unhandled_message", trace_id=trace_id, keys=sorted(msg.keys()))
    item["text"] = ("[she sent something this runtime cannot read — "
                    f"a {', '.join(sorted(k for k in msg if k not in ('message_id','from','chat','date')))}. "
                    "Tell her you could not process it.]")
    return item


def drain_spool(trace: Trace) -> list[dict]:
    """Spool → turn queue, in update_id order, dedup-guarded. The spool file is
    removed only after the item is durably queued."""
    items = []
    for path in spooled():
        try:
            update = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            path.unlink(missing_ok=True)
            continue
        update_id = update.get("update_id")
        if update_id is None or state.already_processed(update_id):
            path.unlink(missing_ok=True)
            continue
        item = prepare(update, trace)
        if item:
            state.enqueue_turn(item)                     # durable first
            items.append(item)
        state.mark_processed(update_id)
        path.unlink(missing_ok=True)
    return items
