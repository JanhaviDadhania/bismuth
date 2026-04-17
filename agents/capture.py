"""
Capture Agent
Pre-fetches Telegram messages in Python, then calls `claude -p` to write
each one to memory/capture.md. No Anthropic API key needed.
"""

import os
import sys
import time
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.telegram import get_updates, download_file
from config import BASE_DIR, MEMORY_DIR


def fetch_messages():
    """Fetch new Telegram messages and pre-process media."""
    result = get_updates(long_poll=30)

    if not result["success"]:
        print(f"Telegram error: {result['error']}")
        return []

    if result["count"] == 0:
        return []

    lines = []
    for msg in result["messages"]:
        if "text" in msg:
            lines.append(f"TEXT: {msg['text']}")

        elif "voice" in msg or "audio" in msg:
            media = msg.get("voice") or msg.get("audio")
            save_path = str(MEMORY_DIR / "capture" / f"voice_{msg['message_id']}.ogg")
            dl = download_file(media["file_id"], save_path)
            if dl["success"]:
                try:
                    from tools.transcribe import transcribe
                    tr = transcribe(save_path)
                    if tr["success"]:
                        lines.append(f"VOICE (transcribed — remove filler words, fix broken sentences, keep meaning): {tr['transcript']}")
                    else:
                        Path(save_path).unlink(missing_ok=True)
                        lines.append(f"VOICE_FAILED: {Path(save_path).name}")
                except Exception:
                    lines.append(f"VOICE FILE: {save_path}")

        elif "photo" in msg:
            photo = msg["photo"][-1]
            save_path = str(MEMORY_DIR / "capture" / f"photo_{msg['message_id']}.jpg")
            download_file(photo["file_id"], save_path)
            if "caption" in msg:
                lines.append(f"PHOTO: {save_path} — {msg['caption']}")
            else:
                lines.append(f"PHOTO: {save_path}")

        elif "video" in msg:
            video = msg["video"]
            save_path = str(MEMORY_DIR / "capture" / f"video_{msg['message_id']}.mp4")
            download_file(video["file_id"], save_path)
            lines.append(f"VIDEO: {save_path}")

        elif "document" in msg:
            doc = msg["document"]
            fname = doc.get("file_name", f"doc_{msg['message_id']}")
            save_path = str(MEMORY_DIR / "capture" / fname)
            download_file(doc["file_id"], save_path)
            lines.append(f"DOCUMENT: {save_path}")

        elif "caption" in msg:
            lines.append(f"TEXT: {msg['caption']}")

        else:
            msg_type = next((k for k in msg if k not in ("message_id", "from", "chat", "date")), "unknown")
            lines.append(f"UNHANDLED: {msg_type}")

    return lines


def run():
    lines = fetch_messages()
    if not lines:
        return

    prompt_path = BASE_DIR / "prompts" / "capture.md"
    system = prompt_path.read_text().replace("memory/", f"{MEMORY_DIR}/")

    user_message = f"""{system}

---

Process these new messages. Append each as a bullet point to {MEMORY_DIR}/capture.md. Create the file if it doesn't exist.

Messages:
{chr(10).join(lines)}"""

    result = subprocess.run(
        ["claude", "-p", user_message, "--dangerously-skip-permissions"],
        cwd=str(BASE_DIR),
    )

    if result.returncode != 0:
        print(f"claude -p exited with code {result.returncode}")
    else:
        print(f"Captured {len(lines)} message(s).")


if __name__ == "__main__":
    print("Capture agent started. Polling for Telegram messages...")
    while True:
        try:
            run()
        except KeyboardInterrupt:
            print("\nCapture agent stopped.")
            break
        except Exception as e:
            print(f"Error: {e}. Retrying in 10s...")
            time.sleep(10)
