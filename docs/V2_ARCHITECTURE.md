# Bismuth v2 — Architecture

Status: **draft for Janhavi's review.** No code has been written.
Companion doc: `docs/V2_REQUIREMENTS.md` — requirements, and the dated decision
log every choice here traces back to.

This document describes *what v2 is*, component by component, plus the exact
life of a single voice note from her mouth to the board. Where a design choice
is still open, it is marked **OPEN** inline rather than silently assumed.

---

## 1. What v2 is

One sentence: **Janhavi speaks into her phone, and a thing she trusts puts it
in the right place and tells her it did.**

Everything else — sub-agents, tracing, the board — exists to make that sentence
true and verifiable.

### The four requirements this serves

- **R1 — the board.** Accepted as-is. v2 feeds it; v2 does not redesign it.
- **R2 — STT.** Accepted as-is. faster-whisper via `tools/transcribe.py`.
- **R3 — no clutter, and trust.** 100% confidence that what she says is saved
  in the right place and appears on the board. This is the load-bearing one.
- **R4 — complete tracing.** Everything Bismuth did, with dates and times,
  permanently.

### The design principle underneath

**Pluggable components.** Every external seam sits behind a narrow interface
with exactly one implementation today: memory layer, input transport, outbound
channel, STT, TTS. Nothing may leak assumptions about which implementation is
behind a seam. This is what makes "GitHub for now, we'll change later" a
configuration change instead of a rewrite.

---

## 2. System overview

```
  ┌──────────────┐
  │   iPhone     │  record → local outbox folder → base64 → PUT
  │  (Shortcut)  │
  └──────┬───────┘
         │  HTTPS (GitHub Contents API)
         ▼
  ┌──────────────────────────┐
  │  bismuth-inbox (private) │   inbox/  ← audio + sidecar
  │  GitHub repo = the queue │   ack/    → status back to the phone
  └──────┬───────────────────┘
         │  poll every ~15s with ETag
         ▼
  ┌───────────────────────────────────────────────────────────┐
  │                    THE RUNTIME (laptop)                    │
  │                                                            │
  │   ingest ──► STT ──► MAIN AGENT ──┬──► memory write        │
  │      │        │       (one session │                       │
  │      │        │        serialized) ├──► spawn sub-agents    │
  │      │        │                    │      (claude -p)      │
  │      │        │                    └──► reply              │
  │      ▼        ▼                            │               │
  │   ═══════════════ TRACE (append-only, never rotated) ═══   │
  └────────────────────────────┬───────────────────────────────┘
                               │
              ┌────────────────┴────────────────┐
              ▼                                 ▼
      ┌───────────────┐               ┌──────────────────┐
      │   Telegram    │               │  bismuth-memory  │
      │ text · voice  │               │  markdown files  │
      │ image · video │               │       ↓          │
      │    links      │               │   board.html     │
      └───────────────┘               └──────────────────┘
```

Two machines, three stores, one direction of flow with one ack path back.

---

## 3. Components

Each is a seam. The implementation named is today's; the interface is what v2
codes against.

| # | Component | Today | Interface it hides behind |
|---|-----------|-------|---------------------------|
| 1 | Capture client | iOS Shortcut | writes a note to the inbox transport |
| 2 | Input transport | private GitHub repo | list / fetch / delete / write-ack |
| 3 | Ingest poller | ETag polling loop | yields notes, one at a time |
| 4 | STT | faster-whisper `base` | audio path → transcript |
| 5 | Main agent | `claude -p`, one session | note → destination + delegation |
| 6 | Sub-agents | `claude -p` subprocesses | instruction → result |
| 7 | Memory layer | markdown in git | read / write / append / list |
| 8 | Outbound channel | Telegram Bot API | text, voice, image, video, link |
| 9 | Trace | append-only JSONL | `log(event_type, **fields)` |
| 10 | Board | `tools/board.py` | memory tree → `board.html` |

---

## 4. The life of one voice note

The normative walkthrough. Every numbered step is also a trace event.

### 4.1 Capture (phone)

1. She triggers the Shortcut — Back Tap, Home Screen icon, Action Button, or
   Siri. **No wake word, ever.** Press-and-hold vs two taps is negotiable; the
   absence of a wake word is not.
2. Audio records. On stop, the Shortcut **writes the file to the local outbox
   first**: `On My iPhone/Shortcuts/bismuth/outbox/`.
3. It writes a sidecar `.json` next to it.
4. It then drains the *entire* outbox — for each pending pair: base64 encode,
   `PUT` to GitHub, and **delete locally only on a 2xx**.

Write-before-send is the whole durability story on the phone. Shortcuts has no
try/catch, so a failed upload simply aborts the shortcut — and the file is
already safely on disk. The next run drains it.

Naming: `<YYYYMMDD>-<HHMMSS>-<short-uuid>` — sortable, collision-free, and it
carries the recording time in the filename.

```json
// 20260829-143012-a3f9c1.json
{
  "client_msg_id": "a3f9c1",
  "recorded_at":   "2026-08-29T14:30:12+05:30",
  "duration_sec":  23.4,
  "device":        "iphone",
  "audio":         "20260829-143012-a3f9c1.m4a"
}
```

`recorded_at` comes from the device, with timezone. R4 wants when she *spoke*,
not when the upload happened.

**Retry, and its one honest hole.** Flush-on-next-note covers almost
everything, since notes come in bursts. Two Shortcuts automations back it up:
Wi-Fi-connects-to-home and Airplane-Mode-off, the closest triggers iOS offers
to "network came back". The residual hole: record several notes offline, then
never record again and never come home — those sit in the outbox. **They are
still visible**, both in the Files app and as notes that never reach `ack/`.
Parked and visible beats silent and lost.

### 4.2 Transport (GitHub)

```
bismuth-inbox/            ← private repo, name TBD
├── inbox/
│   ├── 20260829-143012-a3f9c1.m4a
│   └── 20260829-143012-a3f9c1.json
└── ack/
    └── a3f9c1.json
```

Upload is a single call — `PUT /repos/{owner}/{repo}/contents/inbox/{name}`
with a base64 body. GitHub creates the commit server-side, so the phone needs
no git, and unique filenames mean two writers can never conflict.

Auth is a fine-grained PAT scoped to **contents:write on this one repo**,
stored in the iOS Keychain. Losing the phone means revoking one token.

**GitHub is the durable buffer.** This is the job Telegram used to do: the note
is safe the moment it lands, whether or not the laptop is awake. Worth being
precise — GitHub does not get the note *processed* while the laptop sleeps.
Nothing can; the brain is the laptop. What it buys is that nothing is lost, a
permanent git-history audit trail for R4, and no dependency on Apple.

**Deletion.** Processed notes are removed from `HEAD` only. Blobs stay in
history forever, deliberately: the history *is* the R4 input trail. ~1 MB/day,
under 1 GB/year, which she has accepted explicitly.

### 4.3 Ingest (laptop)

5. Poll `GET /repos/{o}/{r}/contents/inbox` every ~15s with `If-None-Match`.
   Unchanged responses return 304 and **do not count against the 5,000/hr
   authenticated limit**, so the steady-state cost is ~240 requests/hour
   against 5,000.
6. On change, pair each `.m4a` with its `.json` and sort by filename — which
   sorts by recording time.
7. Download to local staging. Trace: `note_received`.

**Ordering guarantee — at-least-once, made safe by idempotency.** The note is
deleted from GitHub *only after* it has been fully processed, an ack written,
and the trace flushed. A crash before that point means the note is fetched
again on restart. A `processed_ids` ledger keyed on `client_msg_id` makes the
second pass a no-op. The alternative — delete first — turns any crash into
silent data loss, which is precisely the R3 failure being designed out.

### 4.4 Transcription

8. Run `tools/transcribe.py` as a subprocess so the whisper model never lives
   inside the runtime process. Trace: `stt_done` with the transcript.

R2 fixes this component. It is still a seam, so it can be swapped, but v2 does
not swap it.

If STT fails: the note is **not** deleted from GitHub, the ack records
`status: "failed"`, and she is told over Telegram. Nothing disappears quietly.

### 4.5 The main agent

9. The transcript goes to a single long-running `claude -p` session.

**Serialized, never batched.** One note, one turn, in order. A note that
elaborates on the previous one is handled as its own instruction. This was an
explicit choice: batching would let note 2 be reinterpreted in note 1's
context, which is right when she's elaborating and wrong when she's switched
topic.

**Session lifetime.** One continuing session, **hard reset at 40% of the
model's context window.** Automatic, no judgment. This differs from v1, which
only *notified* the agent past a token threshold and left the call to it.
Provisional — tracked as issue #21, to be tuned from real usage and possibly
replaced with a summarise-and-carry handoff so continuity survives a reset.

The LLD must state what the 40% is measured against; 40% of 200k and 40% of 1M
are very different amounts of conversation.

**Its job is to think and delegate, and stay available.** It must not tie
itself up doing work, because a second note may arrive seconds later. Her wait
is exactly the main agent's turn length, so the turn is kept short by design.

> **OPEN — does the main agent write the note itself?**
> The strict reading of the architecture is that it delegates *everything*.
> But appending a line to `nexttodo.md` takes milliseconds, and delegating it
> would add a whole sub-agent spawn to the latency of the most common
> operation by far.
> **Recommendation:** the main agent performs the memory write itself and
> delegates only actual *work* (research, code, drafting). Needs her ruling.

### 4.6 Routing

10. The main agent decides the destination.

**Declared by default.** She normally says it: "this is regarding the mirror",
"this is a reminder", "this is a next todo". A declared destination is
*verifiable* — she said "reminder", the ack says `reminders.md`, they match or
they don't. An inferred one is only ever plausible.

**Inference is allowed when she doesn't declare.** That is the point of having
an LLM rather than rigid logic, and it covers mangled transcriptions —
recovering `seldon` from "Sheldon" is a feature.

**The one hard guard: the destination must already exist.** No inventing
folders, no snapping to a near-miss that isn't there. If the resolved
destination is not a real path, the note goes to `others/`.

The memory structure is unchanged from v1 — `projects/`, `miniprojects/`, root
files, `reference/`. No restructuring. All 142 existing destinations remain,
and that is harmless because nothing searches that space blindly.

Trace: `route_decided`, recording destination and whether it was declared or
inferred.

11. Write to memory. Trace: `memory_written` with path and action.

### 4.7 `others/`

`~/bismuth-memory/others/` is the parking folder for anything unroutable.

The sequence is strict: **park first, then ask.** The note is on disk before
any question is asked, so a question that never gets answered still cannot lose
the note.

Bismuth then asks her over Telegram. She replies, and it drains then and
there — conversationally, in the moment, not as a queue that accumulates.
`others/` is visible on the board, and she may also tell Bismuth to clean it up
unprompted.

Moving a tile on the board does **not** move the file. Board interactivity was
considered and rejected; R1 stands.

This is the one piece with a known precedent for going wrong: v1's
`dead_letter/` reached **113 entries** — 15 of them real messages, including
"can you hear me?" from 13 June — precisely because nothing ever surfaced it.
`others/` is surfaced two ways by design: an immediate question, and a visible
count on the board.

### 4.8 Delegation

12. For real work, the main agent writes a clear instruction and spawns a
    `claude -p` sub-agent per subtask. Concurrency is capped, with a queue
    beyond the cap. Trace: `subagent_spawned` with the full instruction.
13. Each sub-agent runs with `--output-format stream-json --verbose`. Every
    tool call and result is captured. Trace: `subagent_event` per line,
    then `subagent_done` or `subagent_failed`.

**Sub-agents are trusted.** Nothing independently verifies that the work
claimed was actually done. This is a known, accepted gap — issue #18.

**Sub-agents cannot ask questions.** v1's mailbox is dropped, so a sub-agent
that gets stuck must complete or fail; it cannot come back for input.

> **OPEN — completion notification.**
> Dropping the mailbox removed both the *question* relay and the *DONE/FAILED*
> relay, because v1 implemented them together. Without some completion signal
> she never learns a task finished.
> **Recommendation:** the question channel stays dropped as she ruled; a
> minimal completion notification survives and is delivered over Telegram like
> any other reply. Needs her ruling.

### 4.9 Reply

14. Bismuth replies over **Telegram**: text, voice notes via `sendVoice`,
    images, video, documents, links.

Prompt rule from her architecture note holds: do not emit 200–300 lines. Write
big things to a file, upload it, send the link, and summarise. Trace:
`reply_sent`, **text only — no audio files are kept.**

Voice replies are generated by `tools/tts.py` (macOS `say`) and delivered as
real playable Telegram voice notes. `say` sounds like `say`; a hosted TTS is a
drop-in swap on the same seam. **OPEN — Q8**, low priority; she'll decide on
first listen.

The external-speaker path from her architecture voice note is **deferred, not
deleted** — it is a second implementation of the outbound seam and can be added
without disturbing anything else.

### 4.10 Acknowledgement

15. Write `ack/{client_msg_id}.json` back to the inbox repo.

```json
{
  "client_msg_id": "a3f9c1",
  "status":        "saved",           // saved | others | failed
  "transcript":    "…",
  "destinations":  [
    { "path": "projects/the_mirror/nexttodo.md", "action": "append" }
  ],
  "on_board":      true,
  "processed_at":  "2026-08-29T14:30:41+05:30",
  "trace_id":      "a3f9c1"
}
```

16. Delete the note from `inbox/` at `HEAD`.

**Acks are deliberately quiet.** They go to GitHub, not Telegram. If every
dictated note buzzed her phone with "saved to …", she would mute the channel
within a week and then miss the messages that matter. Quiet confirmation, loud
conversation.

The phone shows each note's state as **queued → uploaded → saved → on board**.
That progression is what makes R3 checkable rather than a feeling.

### 4.11 Board

17. `tools/board.py` regenerates `board.html` from the memory tree, with
    `others/` shown as a panel with a live count.

Unchanged from v1. R1 froze it and v2 honours that.

---

## 5. Trace (R4)

`~/bismuth-memory/trace/log-YYYY-MM.jsonl` — append-only JSONL, one object per
event, date-partitioned so "what did you do on the 14th" is a file lookup.

**No rotation. Ever. Nothing is unlinked or overwritten.** `rotate_log()` and
`LOG_KEEP` do not carry over from v1.

Every event carries `ts` (ISO 8601, local time with offset) and `trace_id`
(the `client_msg_id`), so every event for one note joins on one key.

| Event | Fields |
|---|---|
| `note_received` | client_msg_id, recorded_at, bytes, filename |
| `stt_done` | transcript, model, duration_sec |
| `route_decided` | destination, mode (declared \| inferred) |
| `memory_written` | path, action, bytes |
| `parked_in_others` | path, reason |
| `subagent_spawned` | task_id, instruction |
| `subagent_event` | task_id, raw stream-json line |
| `subagent_done` / `subagent_failed` | task_id, summary or error |
| `reply_sent` | channel, kind, text |
| `ack_written` | client_msg_id, status, destinations |
| `note_deleted` | client_msg_id |

**Content is tool calls and whatever `claude -p` already emits — nothing
extra.** No reasoning capture, no decision notes. The stream-json output *is*
the trace.

**Per-event size cap.** With no rotation there is nothing else to stop a
runaway loop. v1 has the cautionary tale: a bug in May–June 2026 wrote ~46,000
lines/day and produced a 580 MB generation. (For the record, and correcting an
earlier claim in the requirements doc: v1 has **not** lost any history —
`log.jsonl` and `log.jsonl.1` are both intact and the record since 2026-05-14
is complete.)

**Durability.** The trace currently lives in gitignored scratch, which
contradicts "permanent". Moving it under version control so the git-sync loop
pushes it to GitHub is issue #19, deferred by her and not blocking v2.

---

## 6. State

Runtime state lives on the laptop, outside the memory repo:

- `processed_ids` — the dedup ledger; makes at-least-once safe.
- `session` — the main agent's session id, creation time, running context
  estimate for the 40% rule.
- `subagents` — per task: id, status, spawn time, instruction.
- `subagent_queue` — tasks waiting on the concurrency cap.
- `inbox_etag` — so polls stay cheap.

State is written atomically. Concurrent writers to shared memory files use file
locks, as v1 did.

---

## 7. Failure modes

The R3 section. For each, what happens, and where she can see it.

| Failure | Behaviour | Visible where |
|---|---|---|
| No signal on the phone | Note stays in local outbox; drained on next note, home Wi-Fi, or airplane-mode-off | Files app; never reaches `ack/` |
| GitHub unreachable | Same as above | same |
| Laptop asleep / off | Note waits in GitHub indefinitely | `inbox/` in the repo |
| Runtime crashes mid-note | Note not yet deleted → re-fetched on restart; dedup ledger makes reprocessing a no-op | trace |
| STT fails | Note not deleted; ack `status: failed`; she is told | Telegram + ack |
| Destination doesn't exist | Parked in `others/`, then asked | board + Telegram |
| She never answers the question | Note stays in `others/` | board count |
| Sub-agent fails | Reported to her (pending the OPEN in §4.8) | Telegram + trace |
| Sub-agent silently does nothing | **Not detected** — known accepted gap | issue #18 |
| Rate limit hit | Notes wait in the queue | trace |
| Context reaches 40% | New session starts automatically | trace |
| Runaway work | **No kill switch** — process must be killed by hand | — |

Two of these are unguarded by explicit choice: sub-agent honesty, and the
absence of a stop command. Both are recorded rather than argued.

---

## 8. What v1 has that v2 drops

| Dropped | What it did | Cost of dropping |
|---|---|---|
| **coffeechat** | per-project thinking-partner agent | no brainstorming mode; returns later as a sub-agent if wanted |
| **watchers** | `daily_reminder`, `fs_dropbox`, `twitter_daily` + supervisor | **nothing reaches Bismuth that she didn't say.** No 09:00 reminder surface, no dropbox pickup. `reminders.md` becomes passive |
| **synthetic inbox** | how watchers poked the agent | n/a once watchers go |
| **mailbox** | sub-agent → her questions, and DONE/FAILED relay | stuck sub-agents guess or fail; completion relay see §4.8 OPEN |
| **`/status`** | no-LLM introspection | no way to see what's running without asking the agent |
| **`/halt`** | no-LLM emergency stop | no kill switch |
| **Telegram polling as input** | v1's capture path | replaced by the Shortcut; Telegram stays outbound-only |
| **log rotation** | 10 MB, keep 3 | none — this is the point |
| **batching** | multiple messages per turn | none — serialization is the choice |

This is a much smaller system than v1. That is the intent: R3 is "no clutter,
and a Bismuth I can trust", and every component removed is one that can't fail.

---

## 9. Open items

Blocking the low-level design:

- **Q13 — refactor `harness.py`, or a new lean process?** With watchers,
  mailbox, synthetic inbox, slash commands and coffeechat all gone, several
  hundred lines of v1's harness no longer apply. What v2 still wants is narrow:
  the disk spool, `claude -p` invocation with resumable sessions, stream-json
  parsing, sub-process lifecycle with cap and queue, file locks, state
  persistence. **Recommendation: a new lean process that ports those pieces.**

Raised by this document:

- **§4.5 — does the main agent write the note itself, or delegate even that?**
  Recommendation: it writes; it delegates only real work.
- **§4.8 — completion notification.** Dropping the mailbox removed the
  DONE/FAILED relay along with the question relay. Recommendation: keep a
  minimal completion notification over Telegram.

Not blocking:

- **Q8 — TTS voice.** Decides itself on first listen.
- Inbox repo name, and creating it + the fine-grained PAT.

---

## 10. Build order

Cutover is **hard — v1 stops**, no parallel run. So sequence matters: the
capture path must be proven before v1 is switched off, or there is a window
with no working Bismuth at all.

1. Create the private inbox repo and the fine-grained PAT.
2. Build the ingest poller + trace against a note placed in the repo by hand.
   *Provable without touching the phone.*
3. Build the Shortcut. End-to-end capture now works.
4. Main agent: routing, memory write, `others/`, ack.
5. Telegram outbound + the `others/` question loop.
6. Sub-agent spawning, stream-json capture, completion notification.
7. Board wiring for `others/`.
8. Run both, verify, **then** stop v1.

Steps 1–3 are the trust foundation: once a note reliably gets from her mouth to
`inbox/` and back out as an ack, everything after it is ordinary work.
