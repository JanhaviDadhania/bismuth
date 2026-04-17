# Loophole Fixes — Implementation Plan

Agreed changes to make. Do not start coding until you've read all of this.

---

## SILENT DROPS

### 1. Video messages
**What to change:**
- `agents/capture.py`: add `elif "video" in msg:` handler — download file to `memory/capture/video_<id>.mp4`, append `VIDEO: memory/capture/video_123.mp4` to `lines`
- `prompts/capture.md`: add `video` to message types section and format examples

**Clarification confirmed:** Yes, clarify will move the video file. When clarify processes a `VIDEO:` capture entry, it should move the file from `memory/capture/` to `memory/reference/` (or relevant project support folder), then update `register.md`. Clarify already handles reference routing — just extend it to handle video file paths and move the file as part of routing.

---

### 2. Stickers, polls, location pins, contact cards
**What to change:**
- `agents/capture.py`: add `else:` branch that appends `UNHANDLED: <raw message type>` to `lines` (so the LLM sees it)
- `prompts/capture.md`: add instruction — if you see an `UNHANDLED:` entry, send a Telegram message to janhavi saying "received something I can't process: [type]", do NOT add it to `capture.md`, done once per batch (not one ping per item)

No file locking code needed. Agent handles it in prompt.

---

### 3. Edited messages
**What to change:**
- `tools/telegram.py` line 68: also extract `edited_message` from updates, alongside `message`
- Change: `messages = [u["message"] for u in updates if "message" in u]`
- To: `messages = [u.get("message") or u.get("edited_message") for u in updates if "message" in u or "edited_message" in u]`

No special label. Edited messages appear as `TEXT:` entries in capture.md like any other.

---

### 4. Photo with caption
**What to change:**
- `agents/capture.py` photo handler (lines 51-55): after downloading, check if `"caption" in msg`, if yes append `PHOTO: memory/capture/photo_123.jpg — <caption text>` instead of just the path
- Update `prompts/capture.md` format section to show photo+caption example

---

## MESSAGES LANDING IN WRONG PLACE

### 5. Project name mismatch
**What to change:**
- `config.yaml` `projects:` list: change ALL names to use underscores to match actual folder names:
  - `ai-neuroscience` → `ai_neuroscience`
  - `the-mirror` → `the_mirror`
  - `find-a-job` → `find_a_job`
  - `social-media` → `social_media`
  - `carousee` stays as is
  - `seldon` stays as is
- `prompts/evaluation.md` lines 31-36: update the hardcoded project list to match underscored names

---

### 6. Pending questions matching
**What to change:**
- `prompts/clarify.md` pending questions section: strengthen to say — when matching janhavi's reply to a pending question, if there is ANY ambiguity, do NOT guess. Send a Telegram quoting the original question and the reply, ask for explicit confirmation. Only route once fully confident.

---

### 7. Multi-line messages — numbered format
**Clarification confirmed:** Clarify reads the whole `capture.md` file at once (not line by line). The numbered format change is still needed so multi-line Telegram messages (messages with newlines inside them) are clearly bounded under one number — otherwise multiple lines look like separate bullet entries.

**What to change:**
- `prompts/capture.md`: change format from `-` bullets to numbered entries (`1.`, `2.`, `3.`). Each Telegram message = one numbered entry. Multi-line content stays under its number.
- `prompts/clarify.md`: update wording to reflect numbered format

No changes to `agents/capture.py` — the LLM writes the format based on the prompt.

---

## RACE CONDITION

### 8. Capture + Clarify concurrent file access
**What to change:**
- `prompts/clarify.md`: update Step 1 to say — first rename `capture.md` to `capture_processing.md`, then process `capture_processing.md`, then delete it when done. Capture always appends to `capture.md`; if it doesn't exist after clarify clears it, Python's append mode creates a fresh one.

No code changes needed — the LLM does the file operations via its tools.

---

## DELAYED DELIVERY

### 9. Pending questions in evaluation
**Confirmed:** Evaluation stays read-only. It should report the count of pending questions and list them in the report so janhavi sees them each week. No cleanup, no writing. Janhavi handles them manually.

**What to change:**
- `prompts/evaluation.md`: add a step to read `memory/pending_questions.md` and include all pending items in the report under the existing "Anything that needs your attention" section

---

### 10. Clarify timing in prompt
**What to change:**
- `prompts/clarify.md` line 4: change "You run every 4 hours" → "You run every 1 hour"

---

## SILENT FAILURES

### 11. Voice transcription failure
**What to change:**
- `agents/capture.py` lines 46-48: if `tr["success"]` is False:
  - Delete the `.ogg` file from disk
  - Send Telegram message: "Voice message failed to transcribe — please record and send again"
  - Log a line in `memory/tracking.md`: `[timestamp] voice transcription failed for <filename> — file deleted, janhavi notified`
  - Append nothing to `capture.md`

The tracking.md entry is for debugging (agent adds it, not Python code).

---

### 12. Telegram offset file backup
**What to change:**
- `tools/telegram.py` `_save_offset()`: after writing `telegram_offset.json`, also write same content to `telegram_offset.backup.json`
- `tools/telegram.py` `_load_offset()`: if main file fails (FileNotFoundError or JSON decode error), fall back to `telegram_offset.backup.json`

---

## FILES TO CHANGE — SUMMARY

| File | Changes |
|---|---|
| `agents/capture.py` | Add video handler, else/unhandled handler, photo+caption, transcription failure handling |
| `tools/telegram.py` | Extract edited_message updates, add offset backup |
| `prompts/capture.md` | Add video type, numbered format, UNHANDLED instruction, photo+caption format example |
| `prompts/clarify.md` | Numbered format, fix timing (4h→1h), rename-before-process race fix, stronger pending question matching |
| `prompts/evaluation.md` | Read pending_questions.md, include in report, fix hardcoded project names |
| `config.yaml` | Fix project names to underscores |
