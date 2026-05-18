"""
Text-to-speech for bismuth. Backend: macOS `say`.

Plays through the system default audio output — the same device
robot-io speaker uses by default.

Usage:
    python3 tools/tts.py "hello janhavi"
    python3 tools/tts.py "got it" --voice Samantha
    python3 tools/tts.py "thinking..." --rate 180

If we ever want to swap to a neural TTS (SpeechT5, piper) the swap is
isolated to this file — agents keep calling tts.py and don't care.
"""

import argparse
import subprocess


def speak(text: str, voice: str = None, rate: int = None) -> None:
    cmd = ["say"]
    if voice:
        cmd += ["-v", voice]
    if rate:
        cmd += ["-r", str(rate)]
    cmd.append(text)
    subprocess.run(cmd, check=False)


def main():
    ap = argparse.ArgumentParser(description="Text-to-speech for bismuth")
    ap.add_argument("text", help="What to speak")
    ap.add_argument("--voice", default=None, help="macOS voice name (default: system)")
    ap.add_argument("--rate", type=int, default=None, help="Words per minute")
    args = ap.parse_args()
    speak(args.text, args.voice, args.rate)


if __name__ == "__main__":
    main()
