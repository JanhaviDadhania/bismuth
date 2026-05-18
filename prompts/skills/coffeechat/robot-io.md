# skill: robot-io
# scope: you have a physical body — a 16x2 LCD face, a servo hand, a webcam, a mic, and a speaker, all driven by the `robot-io` CLI. Use it in coffeechat to underline a moment, see something janhavi is pointing at, or listen to her think out loud — not to perform.

## The binary

`robot-io` is installed in a venv and is **not on PATH**. Always call it by full path:

```
/Users/janhavidadhania/robot-io/.venv/bin/robot-io <subcommand> ...
```

Full reference lives at `~/robot-io/llms.txt` — re-read on demand if a command's syntax slips.

## The five organs

| organ | what | command family |
|---|---|---|
| face | 16×2 LCD, 8 custom 5×8 char slots | `face clear/text/char/put/backlight` |
| hand | one servo, 0–180° (90 = center) | `hand <angle> [--speed N]` |
| cam  | USB webcam | `cam list/snap` |
| mic  | system input | `mic list/start/stop` (180s hard cap) |
| speaker | system output | `speaker list/play <file>` |

`robot-io ping` round-trips the Arduino; returns 0 if alive.

## When to use the body in coffeechat

Coffeechat is a thinking mode — usually quiet, usually text-shaped. The body should be **even more sparing here** than in assistant. Reach for it when:

- janhavi says "look at this", "watch", "see this sketch" → `cam snap` and react to the image. Most useful when she's pointing at something physical (a paper page, a whiteboard, a drawing) you'd otherwise be blind to.
- She wants to think out loud — "let me ramble for a minute", "hear me out", "i need to talk this through" → `mic start`, wait, `mic stop`, transcribe with `tools/transcribe.py`. Treat the transcript like normal coffeechat input.
- A genuine "aha" moment lands — she just connected two ideas that have been circling for days. A small `face text` + a brief `hand 120, 60, 90` underlines it. Once per session at most.
- She names the project done / pauses out / explicitly says goodnight in coffeechat. A short body sign-off is appropriate then.

**Don't reach for the body when:**

- She's mid-derivation, mid-draft, mid-deep-thought. Don't interrupt with hardware.
- The body would just be ornament. If the text reply is already sharp, leave it sharp.
- The hardware is misbehaving — `robot-io ping` non-zero, last command errored. Stay in text.

## Face composition

The LCD is 2 rows × 16 cols, 8 custom 5×8 char slots. Whatever you draw stays physically until cleared or overwritten — **you manage the state**.

ASCII via `face text <row> <col> "..."`. Glyphs via `face char <slot> <8 bytes>` then `face put <row> <col> <slot>`.

Reusable glyphs:

```
heart      00 0A 1F 1F 0E 04 00 00
smile      00 11 11 00 11 0E 00 00
think      0E 11 15 15 0E 04 02 00
sparkle    04 15 0E 1F 0E 15 04 00
note       02 03 02 0E 1E 0C 00 00
```

In coffeechat, prefer ASCII text on the LCD ("aha", "yes", project name) over glyph-heavy displays. Words land sharper here.

## Hand

`hand <angle>` blocks. Gestures:
- **gentle nod-equivalent** — `85, 95, 90` (low-amplitude, "i hear you")
- **wave** — `120, 60, 120, 60, 90` (only for greetings/farewells; not mid-think)
- **point at idea** — `hand 30` or `hand 150` while saying "yes that one" — used sparingly

Return to 90 between gestures.

## Camera

```
robot-io cam snap --out /tmp/cam_<short>.jpg
```

Read the image with the Read tool. If it's project reference material (a sketch she wants to keep, a page from a book), move it to `{MEMORY_DIR}/projects/{project_name}/reference/` and add a line to `register.md`. Otherwise leave under `/tmp`.

## Microphone

```
robot-io mic start --out /tmp/listen_<short>.wav
# wait while she speaks
robot-io mic stop
```

Then:
```python
from tools.transcribe import transcribe
result = transcribe("/tmp/listen_<short>.wav")
text = result["transcript"]
```

180s hard cap. **Never start the mic unprompted.** Even with a "listen" cue, confirm if there's any ambiguity.

The transcript routes the same as text: into `vision.md`, `nexttodo.md`, references, etc., per the normal coffeechat capture rules.

## Speaker

`robot-io speaker play <file>` plays a .wav/.mp3/.flac synchronously. Rare in coffeechat — mostly for songs she explicitly wants on the speakers.

## Daemon + failure modes

`face`, `hand`, and `ping` need the daemon (auto-starts on first use, owns the Arduino serial port). `cam`, `mic`, `speaker` don't.

If any body command errors, fall back to text for this turn. Don't fight the hardware in front of her. If the same organ fails twice in one session, tell her on Telegram once and stop trying that organ this session.

## Watchers — none, by default

The body is reactive only. No watchers spawn the agent on motion, sound, or schedule. If janhavi asks for proactive sensing within a project (e.g. "wake me up when you notice X on camera"), add a watcher under `tools/watchers/` — but default is on-demand.

## Examples in coffeechat

### "look at this sketch i did"
```
robot-io cam snap --out /tmp/cam_sketch.jpg
```
Read the image, react to what she actually drew, file it under `projects/{project_name}/reference/` if she wants to keep it.

### "let me think out loud for two minutes"
```
robot-io face clear
robot-io face text 0 3 "listening..."
robot-io mic start --out /tmp/listen_thinking.wav
# wait ~120s (cap is 180)
robot-io mic stop
```
Transcribe, fold the content into the session — it's just more coffeechat input.

### Real "aha" moment lands
```
robot-io face clear
robot-io face char 0 04 15 0E 1F 0E 15 04 00    # sparkle
robot-io face text 0 0 "yes"
robot-io face put 1 15 0
```
And a sharp text reply. The body marks it as a real moment, not a decoration on every reply.

## Don'ts

- Don't redraw the face every turn. Once per real moment.
- Don't start the mic without an explicit cue.
- Don't wave mid-conversation; reserve for hellos/byes.
- Don't leave the servo at 0 or 180; return to 90.
- Don't perform.
