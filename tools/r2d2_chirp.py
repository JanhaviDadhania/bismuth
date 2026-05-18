"""
R2-D2-style chirp synthesizer + player.

Pairs with the robot-io skill: whenever bismuth changes the face or gestures,
fire a short chirp so the body feels engaged, not asleep. Stdlib-only synth
(sine sweeps with vibrato), played through `robot-io speaker`.

Usage:
    python3 tools/r2d2_chirp.py                       # default short chirp
    python3 tools/r2d2_chirp.py --flavor happy
    python3 tools/r2d2_chirp.py --flavor question
    python3 tools/r2d2_chirp.py --flavor ack
    python3 tools/r2d2_chirp.py --flavor sad
    python3 tools/r2d2_chirp.py --no-play --out /tmp/x.wav   # synth only

Flavors:
    short    — 3-5 mixed chirps, neutral. Default companion to face updates.
    happy    — denser, higher, more chirpy. Use after good news / waves.
    question — 2-4 chirps rising in pitch. Use when you're asking.
    ack      — 1-2 short, low-mid. "got it / done".
    sad      — 2-4 falling, low pitch. Use sparingly.
"""

import argparse
import math
import os
import random
import struct
import subprocess
import tempfile
import wave

SR = 22050
ROBOT_IO = os.path.expanduser("~/robot-io/.venv/bin/robot-io")

FLAVORS = {
    "short":    {"chirps": (3, 5), "f_lo": 500, "f_hi": 2200, "vibrato": (10, 20)},
    "happy":    {"chirps": (6, 9), "f_lo": 800, "f_hi": 2600, "vibrato": (12, 22)},
    "question": {"chirps": (2, 4), "f_lo": 400, "f_hi": 1800, "vibrato": (8, 14), "rising": True},
    "ack":      {"chirps": (1, 2), "f_lo": 600, "f_hi": 1400, "vibrato": (10, 16)},
    "sad":      {"chirps": (2, 4), "f_lo": 200, "f_hi": 700,  "vibrato": (5, 9), "falling": True},
}


def chirp(dur, f0, f1, vibrato_rate=14, vibrato_depth=0.25):
    n = int(SR * dur)
    out = []
    for i in range(n):
        t = i / SR
        f = f0 + (f1 - f0) * (t / dur)
        f *= 1 + vibrato_depth * math.sin(2 * math.pi * vibrato_rate * t)
        env = min(1.0, i / (0.01 * SR)) * max(0.0, 1 - (i / n) ** 1.5)
        out.append(env * math.sin(2 * math.pi * f * t))
    return out


def silence(dur):
    return [0.0] * int(SR * dur)


def synth(flavor: str = "short", seed=None):
    cfg = FLAVORS.get(flavor, FLAVORS["short"])
    rng = random.Random(seed)
    n_chirps = rng.randint(*cfg["chirps"])
    samples = []
    for _ in range(n_chirps):
        f0 = rng.uniform(cfg["f_lo"], cfg["f_hi"])
        f1 = rng.uniform(cfg["f_lo"], cfg["f_hi"])
        if cfg.get("rising"):
            f0, f1 = min(f0, f1), max(f0, f1)
        if cfg.get("falling"):
            f0, f1 = max(f0, f1), min(f0, f1)
        samples += chirp(
            rng.uniform(0.06, 0.20), f0, f1,
            vibrato_rate=rng.uniform(*cfg["vibrato"]),
            vibrato_depth=rng.uniform(0.1, 0.32),
        )
        samples += silence(rng.uniform(0.02, 0.08))
    return samples


def write_wav(samples, path):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(
            struct.pack("<h", max(-32767, min(32767, int(s * 28000))))
            for s in samples
        ))


def play(path):
    subprocess.run([ROBOT_IO, "speaker", "play", path], check=False)


def main():
    ap = argparse.ArgumentParser(description="R2-D2 chirp synth + player")
    ap.add_argument("--flavor", default="short", choices=list(FLAVORS.keys()))
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--no-play", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out = args.out or tempfile.NamedTemporaryFile(
        suffix=".wav", delete=False, prefix="r2d2_"
    ).name
    write_wav(synth(args.flavor, args.seed), out)
    print(out)
    if not args.no_play:
        play(out)


if __name__ == "__main__":
    main()
