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

# Reminders tests

These exercise the new `reminders.md` file + daily nudge mechanism. No calendar tool; date is the only field. Default recurring count is **30**.

## R1 — Simple single reminder

**Send:**
> remind me to refactor the harness on june 1

**Expect:**
- `~/bismuth-memory/reminders.md` gets a new line: `- 2026-06-01 — refactor the harness`
- File stays sorted by date.
- Brief Telegram acknowledgement (or silence, both OK).
- No exit tokens.

**Verify:**
```
grep "2026-06-01" ~/bismuth-memory/reminders.md
```

---

## R2 — Recurring reminder (default N=30)

**Send:**
> remind me every monday to do the expense report

**Expect:**
- 30 separate dated entries in `reminders.md`, one per Monday starting from the next upcoming Monday.
- All entries: `- YYYY-MM-DD — do the expense report`
- The 30th entry has `(LAST OF SERIES — ask janhavi if she wants another 30)` appended.
- File is still sorted by date.

**Verify:**
```
grep -c "do the expense report" ~/bismuth-memory/reminders.md   # should be 30
grep "LAST OF SERIES" ~/bismuth-memory/reminders.md
```

---

## R3 — Daily nudge fires

This tests that the harness injects `[daily reminders]` once per day at/after 09:00 and the assistant responds with a Telegram summary.

**Setup**: Make sure `state.last_reminder_check` is empty or yesterday's date so the nudge fires on next tick.

**Trigger**: Restart the harness (current time is well past 09:00, so it'll fire immediately on first tick).

**Expect:**
- `log.jsonl` shows `daily_reminder_fired` event with today's date.
- `state.last_reminder_check` advances to today.
- Assistant gets a batch with `[daily reminders] ...` synthetic at the top.
- Assistant sends **one** Telegram message summarising reminders due today + next 3 days.
- If nothing is due/upcoming, assistant may skip sending (file says "skip if nothing").
- Past-dated entries get pruned from `reminders.md`.

**Verify:**
```
grep "daily_reminder_fired" ~/bismuth-memory/.harness/log.jsonl
cat ~/bismuth-memory/.harness/state.json | grep last_reminder_check
```

---

## R4 — LAST OF SERIES handling

**Setup**: Manually append a line to `~/bismuth-memory/reminders.md` with today's date and the LAST OF SERIES tag:
```
- 2026-05-14 — review the model (LAST OF SERIES — ask janhavi if she wants another 30)
```

**Trigger**: Force a daily nudge (set `state.last_reminder_check` to yesterday and wait for next tick).

**Expect:**
- Assistant's Telegram summary includes "review the model" with the "want another 30?" question.
- When you reply "yes", assistant appends 30 more weekly entries with the new 30th carrying LAST OF SERIES again.

---

## R5 — Pruning past entries

**Setup**: Add a few past-dated reminders to `reminders.md`:
```
- 2026-05-10 — old thing 1
- 2026-05-11 — old thing 2
```

**Trigger**: Daily nudge fires.

**Expect:**
- After the nudge turn completes, the past entries are gone from `reminders.md`.
- Today's and future entries are preserved.

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
