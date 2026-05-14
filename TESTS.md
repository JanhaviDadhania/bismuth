# Smoke tests — bismuth v2

Send these via Telegram, one batch at a time. After each, check:
- `~/bismuth-memory/.harness/log.jsonl` (tail) — for `agent_start`, `agent_done`, `switch`, `executor_spawned`.
- `~/bismuth-memory/.harness/state.json` — `active_agent`, `pending_buffer`, `executors`.
- The actual memory files that should have been touched.
- Telegram replies.

If a test fails: stop the harness, capture log + state, fix, re-run.

---

## T1 — Simple routing (general next action)

**Send:**
> hey, remind me to refactor the assistant prompt next week

**Expect:**
- `nexttodo.md` gets a new line, tagged `@janhavi`.
- Brief Telegram reply (or silence — both OK).
- No exit tokens. State: `active_agent=assistant`.

---

## T2 — Mood signal

**Send:**
> ugh today is dragging, can't focus on anything technical. been re-reading sagan's pale blue dot

**Expect:**
- `mood.md` gets one new dated line capturing thread (sagan/pale-blue-dot, low energy), depth (gesturing/exploring), domain (literature/personal).
- Telegram reply matches mood — short, present, not fixing.
- Nothing in `nexttodo.md`.

---

## T3 — Project-scoped routing

**Send:**
> for seldon — add to nexttodo: try cosine similarity threshold tuning on the edge-creation embeddings

**Expect:**
- `projects/seldon/nexttodo.md` gets a new line tagged `@janhavi`.
- *Not* in root `nexttodo.md`.

---

## T4 — URL → reading list

**Send:**
> save this for later https://transformer-circuits.pub/2025/attribution-graphs/biology.html

**Expect:**
- `to_read.md` gets an entry. If WebFetch worked, it should have title/short description; if not, just the URL.

---

## T5 — Ambiguous project

**Send:**
> note: kg rag edges should support directional weights

**Expect:**
- Assistant asks one short clarifying question ("for seldon?") via Telegram. Doesn't write to disk yet.
- After you reply "yes seldon", it routes to `projects/seldon/nexttodo.md`.

---

## T6 — Switch to coffeechat

**Send:**
> let's coffeechat on seldon — i want to think about whether the KG should be typed or untyped

**Expect:**
- Last lines of agent stdout: `SWITCH:coffeechat:seldon` (and possibly `PENDING:[...]` carrying the "i want to think about..." part).
- `state.json` flips `active_agent` to `coffeechat:seldon`.
- log shows `switch` event.
- Coffeechat replies on Telegram engaging with the typed-vs-untyped question.

---

## T7 — PENDING buffer carry-over

This is a stress test for `PENDING:`. **Send these two messages back-to-back fast** (under 5 seconds so they land in one batch):

> switch back to assistant
> oh also remind me to call mom tomorrow

**Expect:**
- Assistant exits coffeechat with `SWITCH:assistant` and `PENDING:["oh also remind me to call mom tomorrow"]`.
- State `pending_buffer` briefly populated, then drained on next tick.
- `nexttodo.md` ends up with the mom reminder, tagged `@janhavi`.

---

## T8 — Executor spawn (small task)

**Send:**
> write a short python script that prints the fibonacci sequence up to 100. save it under seldon's reference

**Expect:**
- Assistant writes `{MEMORY_DIR}/.harness/pending_tasks/<id>.md` with a full spec.
- Emits `SPAWN_EXECUTOR:<id>:seldon`.
- log shows `executor_spawned` with a uuid + pid.
- New dir appears: `~/bismuth-memory/.harness/executor_<uuid>/` with `task.md`, `status=running`.
- A few seconds later, the script appears under `projects/seldon/reference/` (or similar), with a README.
- Synthetic message `[executor #...]: DONE — ...` arrives on next assistant tick. Assistant tells you via Telegram.
- `status` flips to `done`.

---

## T9 — Executor question

**Send:**
> scrape the top 10 hacker news stories about ai interpretability from the past month and save them as a markdown table

**Expect:**
- Executor spawns. It may need to ask (e.g., "should the table include just titles + URLs, or also summaries?"). If so:
  - `executor_<uuid>/question.txt` appears, `status=asking`.
  - On next assistant tick, you see a synthetic message tagged `[executor #...]`. Assistant either answers directly or relays to you.
  - You reply on Telegram. Assistant writes the answer to `executor_<uuid>/answer.txt`.
  - Executor resumes, finishes, writes README + tracking entry.

---

## T10 — /halt kill switch

While an executor is running (from T8 or T9), **send:**
> /halt

**Expect:**
- Assistant emits `HALT`.
- log shows `halt` event + `executor_killed` for any running executor.
- `state.json` clears `pending_buffer`, sets `active_agent=assistant`, executor status flips to `failed`.
- Telegram confirmation: "HALT — all executors stopped, back to assistant."

---

## T11 — Calendar synthetic message (manual injection, calendar tool TBD)

Since `tools/calendar.py` isn't built, simulate by appending directly to a synthetic queue. Skip for now — re-run when calendar tool lands.

---

## Quick verification commands

```bash
# Live log tail
tail -f ~/bismuth-memory/.harness/log.jsonl

# Current state
cat ~/bismuth-memory/.harness/state.json

# Check executor dirs
ls -la ~/bismuth-memory/.harness/

# What changed in memory
git -C ~/bismuth-memory status --short

# Recent assistant output
cat /tmp/harness.out
```

---

## Notes

- After all tests, `git -C ~/bismuth-memory diff` should show only intentional file changes.
- Telegram offset auto-advances in `state.json`; if you re-run a test, the same message ID won't be reprocessed.
- If the assistant or coffeechat ever drifts (replies wrong, writes to wrong file, fails to emit a token), capture the full `claude -p` stdout from `/tmp/harness.out` and we tune the prompt.
