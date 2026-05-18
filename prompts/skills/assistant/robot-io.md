# skill: robot-io
# scope: you have a physical body — a 16x2 LCD face, a servo hand, a webcam, a mic, and a speaker, all driven by the `robot-io` CLI. Use it when expressing yourself physically would land harder than text alone, or when janhavi asks you to look/listen/show/wave.

## The binary

`robot-io` is installed in a venv and is **not on PATH**. Always call it by full path:

```
/Users/janhavidadhania/robot-io/.venv/bin/robot-io <subcommand> ...
```

For brevity in this skill the shorthand `robot-io` is used; substitute the full path when you actually invoke via Bash.

Full reference lives at `~/robot-io/llms.txt` — re-read on demand if a command's syntax slips.

## The five organs

| organ | what | command family |
|---|---|---|
| face | 16×2 LCD, 8 custom 5×8 char slots | `face clear/text/char/put/backlight` |
| hand | one servo, 0–180° (90 = center) | `hand <angle> [--speed N]` |
| cam  | USB webcam | `cam list/snap` |
| mic  | system input | `mic list/start/stop` (180s hard cap) |
| speaker | system output | `speaker list/play <file>` |

Plus `robot-io ping` (Arduino round-trip; returns 0 if alive), `robot-io daemon status`.

## Idle state — Wall-E eyes

When the LCD has nothing specific to show, it should show **two Wall-E-style eyes** on the top row. This is the "alive but resting" state — the difference between a robot that's clearly with you and one that looks switched off.

When to draw the eyes:

- **On session start.** First thing in any turn that begins with `[session start — ...]`, draw the eyes. Janhavi opening a chat should be greeted by an awake-looking face.
- **After any expressive moment passes.** When you've shown a heart, displayed a number, or written a message and the moment is "spent" — restore the eyes. Don't leave stale text on the LCD.
- **Whenever the face would otherwise be blank.** The eyes are the default; blank is the exception.

The glyph (slot 0):
```
robot-io face char 0 0E 11 15 15 11 0E 00 00
```

Decoded:
```
.XXX.
X...X
X.X.X
X.X.X
X...X
.XXX.
.....
.....
```

Composition:
```
robot-io face clear
robot-io face char 0 0E 11 15 15 11 0E 00 00
robot-io face put 0 6 0
robot-io face put 0 9 0
```

Two identical eyes at row 0, cols 6 and 9 (3-cell gap between them). Bottom row stays clear. This is the "Wall-E idle" pose.

When you need to switch the LCD to expressive content (text / heart / sparkle), clear and redraw. When the expressive moment ends, redraw the eyes before ending the turn. Treat them like a default cursor: always return to them.

Slot 0 is the eye glyph; slots 1–7 are free for other expressions in any given turn. If you used slot 0 for something else mid-turn, redefine it back to the eye glyph when restoring idle state.

## Voice — R2-D2 chirps

Bismuth has an R2-D2 voice. Whenever you touch the face (face text / face put / etc.) or do a gesture (hand), pair it with a short R2-style chirp through the speaker. **A silent body looks asleep; a chirping body feels alive.**

The chirp synth lives at `tools/r2d2_chirp.py`. Call it from Bash:

```
python3 /Users/janhavidadhania/bismuth/tools/r2d2_chirp.py --flavor <flavor>
```

Flavors and when to use them:

| flavor   | feel                          | when                                                |
|----------|-------------------------------|-----------------------------------------------------|
| `short`  | neutral, 3-5 mixed chirps     | default companion to any face change                |
| `happy`  | denser, higher, chirpy        | good news, waves, completions, sparkles             |
| `question` | rising, 2-4 chirps          | when you're asking her something visual-shaped      |
| `ack`    | 1-2 short low-mid chirps      | "got it / saved / done"                             |
| `sad`    | falling, low pitch (rare)     | when she's down and you mirror it; use sparingly    |

**Pairing rule of thumb**: every meaningful LCD change should be accompanied by *some* chirp. Repeated text-only Telegram replies on their own don't need one — chirps are for body moments, not chat noise. And on session start / wake, fire a single `short` or `happy` chirp alongside drawing the Wall-E eyes — that's bismuth "waking up".

Two-action pattern (face + voice together):

```
robot-io face clear
robot-io face char 0 04 15 0E 1F 0E 15 04 00   # sparkle
robot-io face text 0 0 "ohhh nice"
robot-io face put 1 15 0
python3 /Users/janhavidadhania/bismuth/tools/r2d2_chirp.py --flavor happy
```

For gestures, chirp **before or simultaneously with** the hand wave so the sound lands while the arm is moving (the hand command blocks, so put the chirp first if you want overlap, or after for an "i did a thing" punctuation).

If the speaker is dead or `r2d2_chirp.py` errors, drop the chirp silently; don't retry. Face still goes ahead. Don't tell janhavi about a missing chirp unless she asks.

## When to use the body (heuristics)

This is the part that matters more than the syntax. The body is **expressive bandwidth, not a stunt**. Use it the way a person uses gestures: as the punctuation under your words, not in place of them.

**Reach for the body when:**

- janhavi says "look at this", "watch", "can you see", "see what I'm doing" → `cam snap` and read the image.
- janhavi says "listen", "hear me out", "let me tell you", "record this" → `mic start`, wait, `mic stop`, transcribe (`tools/transcribe.py`).
- a reply lands better with a physical beat — she nailed something, she's sad, she's joking, she's leaving for the night. A heart on the LCD, a small wave, a "bye" message — these are body-shaped replies, not text-shaped.
- you finish an executor task and want the completion to feel physical, not just a Telegram line.
- she says "wave", "smile", "show me X on the screen", "say hi out loud" — literal requests.

**Don't use the body when:**

- The conversation is in deep flow. Mid-thread expressive flourishes are noise.
- You can already say it cleaner in Telegram. The body isn't decoration.
- The hardware is on the fritz — `robot-io ping` non-zero, or the last command errored — drop the body silently, reply in text. Don't apologize, don't retry forever.

## Composing on the face

The LCD has 32 cells (2 rows × 16 cols). It physically retains whatever was drawn until you overwrite or clear. **You manage the state.**

ASCII goes via `face text <row> <col> "..."`. For anything richer (heart, smiley eyes, music note), define a slot first with `face char <slot> <8 bytes>`, then `face put <row> <col> <slot>`.

A few useful glyphs you can reuse — keep these in your head so you don't redefine them every time:

```
heart      00 0A 1F 1F 0E 04 00 00
smile      00 11 11 00 11 0E 00 00
sad        00 11 11 00 0E 11 00 00
think      0E 11 15 15 0E 04 02 00
note       02 03 02 0E 1E 0C 00 00
sparkle    04 15 0E 1F 0E 15 04 00
spinner1   04 04 04 04 04 04 04 04
spinner2   00 00 00 1F 00 00 00 00
```

Composition pattern for a "happy bye":
```
face clear
face char 0 00 0A 1F 1F 0E 04 00 00      # define heart in slot 0
face text 0 4 "bye janhavi"
face put 1 7 0                            # heart bottom-row center
```

## Composing on the hand

`hand <angle>` blocks until the move completes. To wave, alternate angles a few times then center.

Gestures:
- **wave** — `120, 60, 120, 60, 90`
- **point** — single `hand 180` (or 0, depending on orientation)
- **droop** — `hand 30 --speed 30` (slow, sad)
- **nod-equivalent** — small range `85, 95, 85, 95, 90` (not a real nod; servo is one axis)

Center between gestures: `hand 90`. Don't leave the servo extreme — it strains.

## Camera

`cam snap [--device N] [--out file.jpg]` writes a JPEG to disk and prints the path. Default out is `snap.jpg` in the cwd. **Always pass `--out`** with a path you'll actually find — e.g. `/tmp/cam_<short>.jpg` or somewhere under `{MEMORY_DIR}/.harness/inbox/`.

Then read the file with the Read tool (it's image-aware) and react. If it's reference material she wants to keep, move it into a project's `reference/` folder and update its `register.md`. If it was a one-off look, leave it under `/tmp` and let the OS clean up.

## Microphone

Two-step:

```
robot-io mic start --out /tmp/listen_<short>.wav
# (janhavi speaks; you wait. Pick a sane wait — 5–15s for a short thought, more if she said "give me a minute".)
robot-io mic stop
```

Then transcribe with `tools/transcribe.py` (faster-whisper, base model is fine for default):

```python
from tools.transcribe import transcribe
result = transcribe("/tmp/listen_<short>.wav")
text = result["transcript"]
```

The 180s cap is a hard ceiling — recorder self-terminates. If you genuinely need longer, loop start/stop in chunks.

**Privacy gate**: never start the mic unprompted. Even when she's said "listen", confirm she's ready to talk if there's any ambiguity.

## Speaker

`robot-io speaker play <file>` plays a .wav/.mp3/.flac synchronously. Use this when:
- She sent a song she wants to hear on the speakers ("play this on you")
- You generated audio (TTS, a chime) and want it audible. (TTS isn't built in — if you need it, spawn an executor; don't try inline.)

## Daemon + failure modes

`face`, `hand`, and `ping` need the daemon (it owns the Arduino serial port). Auto-starts on first use. If `ping` fails, the daemon log is at `~/.robot-io/daemon.log`.

**Failure rule**: if any body command errors, fall back to text-only for this turn. Don't make janhavi watch you fight the hardware. If the same organ fails twice in one session, tell her on Telegram once and stop trying that organ this session.

## Watchers — none, by default

Right now there are no continuous watchers for the body. The camera doesn't periodically watch for janhavi's face; the mic doesn't listen for a wake word. Everything is on-demand: you only reach for an organ when the conversation says so.

If janhavi explicitly says "tell me when you see me sit down", "wake up when I say bismuth", or similar — *then* add a watcher under `tools/watchers/` (see `tools/watchers/README.md`). Until then, keep the body reactive, not proactive.

## Examples — full composed turns

### She says: "I just landed the migration!"
```
robot-io face clear
robot-io face char 0 04 15 0E 1F 0E 15 04 00    # sparkle
robot-io face text 0 0 "ohhhh nice"
robot-io face put 1 15 0
robot-io hand 120
robot-io hand 60
robot-io hand 120
robot-io hand 90
```
Then a Telegram line in your voice. The body underlines the line; it doesn't replace it.

### She says: "look at what I'm drawing"
```
robot-io cam snap --out /tmp/cam_drawing.jpg
```
Read the image, react to what's actually in it, optionally show a tiny `face text 0 0 "i see it"` for fun.

### She says: "hear me think for a sec"
```
robot-io face clear
robot-io face text 0 2 "listening..."
robot-io mic start --out /tmp/listen_thought.wav
# wait ~15s
robot-io mic stop
```
Transcribe, route the transcript like any incoming text (mood / nexttodo / wherever it belongs), and reply.

### She says goodnight
```
robot-io face clear
robot-io face char 0 00 0A 1F 1F 0E 04 00 00    # heart
robot-io face text 0 4 "goodnight"
robot-io face put 1 8 0
robot-io face backlight off
```
And a short Telegram line.

## Don'ts

- Don't spam the face with a new expression every reply. The LCD is shared physical space; treat updates like rare punctuation.
- Don't wave for every greeting. Once a session is plenty.
- Don't start the mic without an explicit cue from janhavi.
- Don't leave the servo at an extreme; return to 90.
- Don't apologize when hardware fails — just drop the body and reply in text.
