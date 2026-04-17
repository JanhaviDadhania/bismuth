"""
Transcribe Tool
Transcribes audio/video files to text using faster-whisper.
Model is loaded once and cached for the lifetime of the process.

Install: pip install faster-whisper
"""

from faster_whisper import WhisperModel

# ─────────────────────────────────────────────
# Model Cache
# ─────────────────────────────────────────────

_model = None

def _get_model(model_size: str = "base") -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _model


# ─────────────────────────────────────────────
# Tool Functions
# ─────────────────────────────────────────────

def transcribe(file_path: str, model_size: str = "base") -> dict:
    """Transcribe an audio or video file and return the transcript as plain text."""
    try:
        model = _get_model(model_size)
        segments, _ = model.transcribe(file_path)
        transcript = " ".join(segment.text.strip() for segment in segments)
        return {"success": True, "transcript": transcript}
    except FileNotFoundError:
        return {"success": False, "error": f"File not found: {file_path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
# Tool Descriptions
# ─────────────────────────────────────────────

TOOL_DESCRIPTIONS = [
    {
        "name": "transcribe",
        "description": "Transcribe an audio or video file to plain text. Supports voice messages, audio files, and video files. Call this after downloading a file from Telegram using download_file.",
        "parameters": {
            "file_path": {
                "type": "string",
                "description": "Local path to the audio or video file to transcribe"
            },
            "model_size": {
                "type": "string",
                "description": "Whisper model size: tiny, base, small, medium, large-v3. Default is base.",
                "default": "base"
            }
        }
    }
]


# ─────────────────────────────────────────────
# Tool Router
# ─────────────────────────────────────────────

TOOLS = {
    "transcribe": transcribe,
}


def run_tool(tool_name: str, arguments: dict) -> dict:
    """Call a tool by name with the given arguments."""
    if tool_name not in TOOLS:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}
    return TOOLS[tool_name](**arguments)
