"""
Telegram Tool
Send and receive messages, files, photos, audio, video via Telegram Bot API.
Offset state is managed internally — callers never deal with it.
Token is read from TELEGRAM_BOT_TOKEN environment variable.
"""

import os
import json
import requests

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

OFFSET_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory", "telegram_offset.json")
BASE_URL = "https://api.telegram.org/bot{token}/{method}"


def _token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise EnvironmentError("TELEGRAM_BOT_TOKEN environment variable is not set")
    return token


def _url(method: str) -> str:
    return BASE_URL.format(token=_token(), method=method)


OFFSET_BACKUP_FILE = OFFSET_FILE.replace(".json", ".backup.json")


def _load_offset() -> int:
    for path in (OFFSET_FILE, OFFSET_BACKUP_FILE):
        try:
            with open(path, "r") as f:
                return json.load(f).get("offset", 0)
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    return 0


def _save_offset(offset: int):
    os.makedirs(os.path.dirname(OFFSET_FILE), exist_ok=True)
    data = json.dumps({"offset": offset})
    for path in (OFFSET_FILE, OFFSET_BACKUP_FILE):
        with open(path, "w") as f:
            f.write(data)


# ─────────────────────────────────────────────
# Tool Functions
# ─────────────────────────────────────────────

def get_updates(long_poll: int = 30) -> dict:
    """Fetch new messages since last call. Returns raw Telegram message objects.
    Offset is managed internally — only unseen messages are returned.
    long_poll controls how many seconds Telegram holds the connection waiting for a message.
    Set to 0 for an instant check with no waiting."""
    try:
        offset = _load_offset()
        response = requests.get(_url("getUpdates"), params={"offset": offset, "timeout": long_poll}, timeout=long_poll + 5)
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            return {"success": False, "error": data.get("description", "Unknown error")}

        updates = data.get("result", [])

        if updates:
            _save_offset(updates[-1]["update_id"] + 1)

        messages = [u.get("message") or u.get("edited_message") for u in updates if "message" in u or "edited_message" in u]
        return {"success": True, "messages": messages, "count": len(messages)}

    except Exception as e:
        return {"success": False, "error": str(e)}


def download_file(file_id: str, save_path: str) -> dict:
    """Download a file from Telegram by file_id and save it to save_path.
    Use this for voice, audio, video, photo, document before processing."""
    try:
        # Step 1: get file path on Telegram servers
        response = requests.get(_url("getFile"), params={"file_id": file_id})
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            return {"success": False, "error": data.get("description", "Unknown error")}

        file_path = data["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{_token()}/{file_path}"

        # Step 2: download bytes
        file_response = requests.get(download_url)
        file_response.raise_for_status()

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(file_response.content)

        return {"success": True, "saved_to": save_path}

    except Exception as e:
        return {"success": False, "error": str(e)}


def send_message(text: str, chat_id: str = None) -> dict:
    """Send a text message to a chat. chat_id defaults to TELEGRAM_CHAT_ID env var."""
    try:
        chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        if not chat_id:
            return {"success": False, "error": "No chat_id provided and TELEGRAM_CHAT_ID is not set"}
        response = requests.post(_url("sendMessage"), json={"chat_id": chat_id, "text": text})
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            return {"success": False, "error": data.get("description")}
        return {"success": True, "message_id": data["result"]["message_id"]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def send_photo(chat_id: str, file_path: str, caption: str = "") -> dict:
    """Send a photo to a chat."""
    try:
        with open(file_path, "rb") as f:
            response = requests.post(
                _url("sendPhoto"),
                data={"chat_id": chat_id, "caption": caption},
                files={"photo": f}
            )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            return {"success": False, "error": data.get("description")}
        return {"success": True, "message_id": data["result"]["message_id"]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def send_document(chat_id: str, file_path: str, caption: str = "") -> dict:
    """Send any file as a document to a chat (pdf, txt, zip, etc.)."""
    try:
        with open(file_path, "rb") as f:
            response = requests.post(
                _url("sendDocument"),
                data={"chat_id": chat_id, "caption": caption},
                files={"document": f}
            )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            return {"success": False, "error": data.get("description")}
        return {"success": True, "message_id": data["result"]["message_id"]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def send_video(chat_id: str, file_path: str, caption: str = "") -> dict:
    """Send a video file to a chat."""
    try:
        with open(file_path, "rb") as f:
            response = requests.post(
                _url("sendVideo"),
                data={"chat_id": chat_id, "caption": caption},
                files={"video": f}
            )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            return {"success": False, "error": data.get("description")}
        return {"success": True, "message_id": data["result"]["message_id"]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def send_audio(chat_id: str, file_path: str, caption: str = "") -> dict:
    """Send an audio file to a chat."""
    try:
        with open(file_path, "rb") as f:
            response = requests.post(
                _url("sendAudio"),
                data={"chat_id": chat_id, "caption": caption},
                files={"audio": f}
            )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            return {"success": False, "error": data.get("description")}
        return {"success": True, "message_id": data["result"]["message_id"]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def send_voice(chat_id: str, file_path: str) -> dict:
    """Send a voice message (.ogg) to a chat."""
    try:
        with open(file_path, "rb") as f:
            response = requests.post(
                _url("sendVoice"),
                data={"chat_id": chat_id},
                files={"voice": f}
            )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            return {"success": False, "error": data.get("description")}
        return {"success": True, "message_id": data["result"]["message_id"]}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
# Tool Descriptions
# ─────────────────────────────────────────────

TOOL_DESCRIPTIONS = [
    {
        "name": "get_updates",
        "description": "Fetch new messages from Telegram since the last time this was called. Returns raw Telegram message objects. Messages can contain text, voice, audio, video, photo, or document. Only the capture agent should call this. Uses long polling — blocks until a message arrives or long_poll seconds pass.",
        "parameters": {
            "long_poll": {
                "type": "integer",
                "description": "Seconds to wait for new messages before returning empty. Default is 30. Set to 0 for an instant non-blocking check.",
                "default": 30
            }
        }
    },
    {
        "name": "download_file",
        "description": "Download a file from Telegram to local disk using its file_id. Call this when a message contains a voice, audio, video, photo, or document field. Returns the local path where the file was saved.",
        "parameters": {
            "file_id": {
                "type": "string",
                "description": "The file_id from the Telegram message (e.g. message.voice.file_id)"
            },
            "save_path": {
                "type": "string",
                "description": "Local path to save the file to, e.g. memory/voice_001.ogg"
            }
        }
    },
    {
        "name": "send_message",
        "description": "Send a plain text message to janhavi on Telegram. chat_id is optional — defaults to TELEGRAM_CHAT_ID env var, so you can omit it.",
        "parameters": {
            "text": {"type": "string", "description": "Message text"},
            "chat_id": {"type": "string", "description": "Telegram chat ID. Omit to use the default (TELEGRAM_CHAT_ID env var).", "default": ""}
        }
    },
    {
        "name": "send_photo",
        "description": "Send an image file to a Telegram chat.",
        "parameters": {
            "chat_id": {"type": "string", "description": "Telegram chat ID"},
            "file_path": {"type": "string", "description": "Local path to the image file"},
            "caption": {"type": "string", "description": "Optional caption"}
        }
    },
    {
        "name": "send_document",
        "description": "Send any file (pdf, txt, zip, csv, etc.) to a Telegram chat as a document.",
        "parameters": {
            "chat_id": {"type": "string", "description": "Telegram chat ID"},
            "file_path": {"type": "string", "description": "Local path to the file"},
            "caption": {"type": "string", "description": "Optional caption"}
        }
    },
    {
        "name": "send_video",
        "description": "Send a video file to a Telegram chat.",
        "parameters": {
            "chat_id": {"type": "string", "description": "Telegram chat ID"},
            "file_path": {"type": "string", "description": "Local path to the video file"},
            "caption": {"type": "string", "description": "Optional caption"}
        }
    },
    {
        "name": "send_audio",
        "description": "Send an audio file to a Telegram chat.",
        "parameters": {
            "chat_id": {"type": "string", "description": "Telegram chat ID"},
            "file_path": {"type": "string", "description": "Local path to the audio file"},
            "caption": {"type": "string", "description": "Optional caption"}
        }
    },
    {
        "name": "send_voice",
        "description": "Send a voice message (.ogg) to a Telegram chat.",
        "parameters": {
            "chat_id": {"type": "string", "description": "Telegram chat ID"},
            "file_path": {"type": "string", "description": "Local path to the .ogg voice file"}
        }
    }
]


# ─────────────────────────────────────────────
# Tool Router
# ─────────────────────────────────────────────

TOOLS = {
    "get_updates": get_updates,
    "download_file": download_file,
    "send_message": send_message,
    "send_photo": send_photo,
    "send_document": send_document,
    "send_video": send_video,
    "send_audio": send_audio,
    "send_voice": send_voice,
}


def run_tool(tool_name: str, arguments: dict) -> dict:
    """Call a tool by name with the given arguments."""
    if tool_name not in TOOLS:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}
    return TOOLS[tool_name](**arguments)
