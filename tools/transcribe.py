"""
Transcribe Tool
Transcribes audio/video files to text using faster-whisper.

Importable (used by the robot-io skill flows):
    from tools.transcribe import transcribe
    result = transcribe("/path/file.wav")   # {"success": bool, "transcript"/"error": str}

CLI (used by the harness, so the whisper model never lives inside the
harness process):
    python3 tools/transcribe.py /path/file.ogg [--model-size base]
    → prints one JSON object to stdout

Install: pip install faster-whisper
"""

import argparse
import json
import sys

from faster_whisper import WhisperModel

_model = None


def _get_model(model_size: str = "base") -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _model


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


def main() -> int:
    ap = argparse.ArgumentParser(description="Transcribe an audio/video file; prints JSON")
    ap.add_argument("file", help="path to the audio or video file")
    ap.add_argument("--model-size", default="base",
                    help="whisper model size: tiny, base, small, medium, large-v3")
    args = ap.parse_args()
    result = transcribe(args.file, args.model_size)
    print(json.dumps(result))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
