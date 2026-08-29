# Bismuth v2 — Requirements & Decision Log

Status: **open — requirements captured, architecture under discussion.**
Owner: Janhavi. Bismuth (this repo) implements; Janhavi confirms each decision.

How this file works: requirements are fixed unless Janhavi changes them. Every
architecture question gets asked, answered, and — once she confirms one way —
logged under **Decisions** with the date. Nothing gets built on an unlogged
decision.

---

## The four requirements

### R1 — Minimal visualisation (the board)
The current infinite-canvas board (`tools/board.py` → `board.html`) is
**accepted as-is**. Janhavi is happy with it. v2 does not redesign the board.
Treat it as a fixed surface: v2 may feed it more/better data, must not clutter
it or restyle it.

### R2 — STT
The current speech-to-text path is **accepted as-is**: Telegram voice note →
downloaded to `.harness/inbox/` → `tools/transcribe.py` (faster-whisper,
`base`, CPU int8) → transcript injected into the agent. v2 does not swap the
STT engine. Whatever the new front-end is, it must land audio in a form this
same path can consume.

### R3 — No clutter, and a Bismuth she can trust
The load-bearing requirement. When Janhavi says something to Bismuth, she must
have **100% confidence** that it (a) got saved, (b) got saved in the *right*
place in memory, and (c) shows up on the board. If she can't trust that, she
goes back to writing notes by hand and Bismuth is pointless.

Trust here means *verifiable*, not *probably fine*. It implies:
- an explicit acknowledgement back to her, naming where the thing landed
- nothing silently dropped — no message may end its life unprocessed
- no duplicate/competing surfaces (that's the "no clutter" half)

Known evidence this is currently broken, as of 2026-08-28:
- `~/bismuth-memory/.harness/dead_letter/` holds **113 entries**, 15 of them
  real user messages (e.g. "can you hear me?" from 2026-06-13) that were never
  processed and never reported back to her.
- 55 dead-lettered *batches* — multi-message drops.
- Nothing tells her when a message is dead-lettered.

### R4 — Complete tracing and logging
Every single thing Bismuth did, with **date and time**, permanently queryable.
"What did you do on the 14th, and why?" must have an answer.

Known gaps as of 2026-08-28:
- `.harness/log.jsonl` is rotated at 10 MB, keep 3 → **history is deleted**.
  (`log.jsonl.1` is currently 580 MB, so rotation isn't even behaving.)
- Harness events are logged, but the agent's own actions (which tool it called,
  which file it wrote) live only in per-session transcripts and per-executor
  `stdout.log`s — not in one timeline.
- No single "what happened, when" view.

---

## Architecture questions under discussion

- **Q1 — Input transport.** *Resolved 2026-08-28 — see Decisions.*

- **Q2 — The memory layer itself.** *Resolved 2026-08-28: GitHub for now.*
  Markdown in git stays. Tracked as
  [issue #20](https://github.com/JanhaviDadhania/bismuth/issues/20) for a later
  swap. Hard constraint that survives any swap: memory must present as normal
  local files on the Mac.

- **Q3 — Where the local outbox queue lives on the phone.**
  *Resolved 2026-08-28 — see Decisions.*

---

## Decisions

<!-- Append only. Format: - **YYYY-MM-DD — <topic>.** <decision>. Why: <reason>. -->

- **2026-08-28 — Versioning.** Bismuth is versioned on GitHub with annotated
  tags. `main` is tagged **`v1.0`** as-is — the shipped three-agent Telegram
  harness. Tag pushed to origin. Why: freezes a known-good reference point
  without disturbing in-flight work.

- **2026-08-28 — Do not merge `board` into `main`.** v2 development continues
  on the `board` branch. `main` stays at the v1.0 state. Why: Janhavi's
  explicit call — `board` is in-flight, and v1 must stay frozen and clean.

- **2026-08-28 — `docs/v2/` → `docs/v1/`, on `main` only.** Those docs describe
  the system now called v1, so the directory name was backwards. Done via PR
  #17 into `main` (org rule: no direct commits to `main`), *not* on `board`.
  `V2_PLAN.md` keeps its filename for history; `docs/v1/README.md` explains
  why. Note: the `v1.0` tag predates this rename by one commit — harmless, the
  tag marks code state.

- **2026-08-28 — This file lives on `board`.** v2 requirements and decisions
  travel with v2 development, not with frozen `main`.

- **2026-08-28 — Transport: GitHub is the server.** An iPhone client records
  audio and `PUT`s it to a private GitHub repo via the Contents API (one
  HTTPS call, no git on the phone, fine-grained PAT scoped to that one repo).
  Bismuth polls with an ETag every ~15s, downloads, runs it through the
  existing `tools/transcribe.py` path, processes it, then deletes the file.
  Why: GitHub is the durable buffer, so the Mac being asleep can't lose a
  note — the one job Telegram was really doing. No tunnel, no Tailscale,
  nothing listening on the Mac.

- **2026-08-28 — Delete from HEAD, keep the history.** Processed notes are
  removed from HEAD only; the audio blobs stay in git history forever.
  Janhavi: "<1gb a year is nothing." No history truncation, no periodic
  re-init. Why: the history *is* the R4 input audit trail — every note you
  ever recorded, with a timestamp, permanently. Cost is ~1 MB/day.

- **2026-08-28 — ACK mechanism confirmed.** After processing, Bismuth writes
  `ack/<uuid>.json` back to the same repo — status, the memory path it landed
  in, and whether it's on the board. The client polls `ack/` and shows each
  note as **queued → uploaded → saved → on board**. Why: R3. Without an ACK
  she is trusting silence, which is the exact failure being fixed.

- **2026-08-28 — Local outbox queue confirmed.** The client writes audio to a
  local outbox *before* attempting upload, and only deletes on a 2xx. Nothing
  is ever in flight without being on disk first. Why: R3 — a dropped note with
  no signal is the same failure as a dropped note in `dead_letter/`.

- **2026-08-28 — Sidecar metadata.** Each note ships a `.json` sidecar with
  `client_msg_id`, `recorded_at` (device local time + timezone) and duration.
  Why: commit time is when it *uploaded*; R4 wants when she *spoke*.

- **2026-08-28 — Outbox is local, not iCloud: `On My iPhone/Shortcuts/bismuth/outbox/`.**
  Janhavi's iCloud storage is full and she is not buying more. Why it doesn't
  matter: the outbox lives on the phone's own storage, and processed notes are
  deleted after upload, so steady state is a near-empty folder holding ~1 MB/day
  at worst.
  Consequence: the Mac cannot see the outbox, so **the Shortcut itself does the
  GitHub `PUT`** — base64 encode, PAT, and the drain loop all live in the
  Shortcut (~15 actions, not 5). This collapses the earlier local-vs-iCloud
  fork: GitHub is the single transport, exactly as originally proposed, with no
  Apple dependency and no recurring cost.

- **2026-08-28 — Capture path settled end to end (Janhavi confirmed the
  Shortcuts actions exist).** Record on phone → save to local outbox folder →
  Shortcut `PUT`s to the private GitHub inbox repo → laptop polls GitHub and
  pulls. The local folder is the queue. This half of the pipeline is closed;
  remaining design work is on the *processing* side.

## Evidence for R3 — the routing surface is the trust problem

Measured in `~/bismuth-memory/` on 2026-08-28:

- **142 candidate markdown destinations** a single note could be routed to:
  12 at root, 120 across `projects/` + `miniprojects/` (depth ≤ 2), 10 in
  `reference/`.
- **18 projects, but only ~5 are live.** Last real touch:
  `find_a_job` (08-25), `social_media` (08-19), `nostayidiot` (08-06),
  `the_mirror` (07-22), `novel` (07-13). The other 14 all read 2026-07-07 —
  that's a bulk restructure timestamp, not activity.
- Two competing project tiers (`projects/` and `miniprojects/`) mean every note
  carries an extra "is this a project or a miniproject?" decision.
- Duplicate destination classes: `mood.md`, `to_read.md` and `summary.md` exist
  both at root *and* per project.
- Runtime cruft committed into the memory repo: `telegram_offset.json`,
  `telegram_offset.backup.json`, `bismuth_talking_archive.txt`.

Conclusion: a 142-way *inferred* routing decision is a guess, and a guess is
what she can't trust. Bismuth proposed slimming the destination set;
**Janhavi rejected that** and solved it from the other side — see the
declared-destination decision below. The 142 destinations stay; nothing infers
its way through them.

## Open empirical check (blocks writing the Shortcut recipe)

*Confirmed done by Janhavi 2026-08-28.* Actions relied on:
- **Record Audio** — if absent, capture becomes Voice Memos → Share Sheet →
  Shortcut (three taps, and it can't live on the Action Button).
- **Save File** — must allow picking `On My iPhone` as the destination, with
  "Ask Where to Save" toggled off.
- **Get Contents of Folder** (or equivalent) — needed for the drain loop.
- **Base64 Encode**, **Get Contents of URL** — for the `PUT`.

The whole design rests on these five.

- **2026-08-28 — No memory restructuring. Rejected.** Bismuth proposed
  collapsing 142 destinations to ~20 (one project tier, folded root files,
  dormant projects archived). Janhavi said no. The existing structure —
  `projects/`, `miniprojects/`, root files, `reference/` — stays exactly as
  it is. Do not re-propose this.

- **2026-08-28 — Routing is declared by default.** Every voice note normally
  states its own destination: "this is regarding <project>", "this is a
  reminder", "this is a next todo". Why: a declared destination is verifiable
  (she said "reminder", the ACK says `reminders.md`, they match or they don't),
  where an inferred one is only ever plausible. It also makes the
  142-destination count harmless, since nothing is searching that space.
  **Relaxed later the same day (see Q4/Q5):** when she *doesn't* state it,
  Claude may infer — that's the point of having an LLM rather than rigid logic.
  The guard is that the inferred destination must be a folder that already
  exists; otherwise `others/`.

- **2026-08-28 — `others/` is the parking folder.** When the destination isn't
  stated — she forgot, or Bismuth genuinely can't tell — the note goes to
  `~/bismuth-memory/others/` and **Bismuth asks her**. It never picks a
  destination to avoid asking.

## Open questions on the declared-routing design

- **Q4 / Q5 — Routing strictness.** *Resolved 2026-08-28: inference is
  allowed.* Claude may guess the destination — including recovering a mangled
  project name — but the guess **must land on a folder that already exists**.
  If it doesn't match anything real, the note goes to `others/`. No new folders
  get invented, no near-miss snapping to a destination that isn't there.
  Janhavi: whisper mangling hasn't been a problem in practice, the agent is
  usually smart enough, and the model is swappable if it isn't.
  *Residual risk, accepted:* a note that mentions a project in passing without
  it being the destination can still be routed there.

- **Q6 — Draining `others/`.** *Resolved 2026-08-28.* Bismuth parks the note in
  `others/` **first**, then asks her about it over the outbound channel. She
  replies and it drains then and there — no queue that accumulates. `others/`
  is visible on the board, and she may also tell Bismuth to clean it up
  unprompted. See Q11 on whether she moves tiles herself.

- **Q7 — The outbound channel.** *Resolved 2026-08-28: **Telegram**.*
  "Fine let's keep telegram. things becomes easy." It carries voice notes both
  ways, images, video, anything; the token, chat ID and `tools/telegram_cli.py`
  already work. Build cost ~zero.
  Consequences: (a) **the speaker + TTS-to-external-speaker path from the
  architecture voice note is deferred, not deleted** — under pluggable
  components it's a second implementation of the outbound seam, addable later;
  (b) Telegram also stays available as a *fallback input*, so if the Shortcut
  breaks she still has a working path in; (c) the earlier
  quiet-ACKs-vs-loud-replies split still applies — ACKs go to GitHub `ack/`,
  real replies go to Telegram, so the channel doesn't get muted.
  WhatsApp remains ruled out (24-hour window kills proactive sending).
  Self-hosted ntfy.sh remains the fallback if Telegram is ever dropped.

- **Q10 — Batch or serialize?** *Resolved 2026-08-28: **serialize**.* No
  batching. Each note is its own turn, in order. Consequence accepted: a note
  that elaborates on the previous one is handled as a separate instruction.

- **Q11 — Board interactivity.** *Resolved 2026-08-28: no.* Moving a tile on
  the board does not move the file. Notes simply stay in `others/` until she
  tells Bismuth where they go, or Bismuth asks. R1 stands — the board is not
  touched.

---

## Log retention — DECIDED

- **2026-08-28 — No rotation. Ever. Logs are permanent.** Janhavi: "no rotation
  at all. I want logs to be present always." Hard constraint on the v2
  architecture. `rotate_log()` and `LOG_KEEP` do not carry over. Files are
  date-partitioned (`log-YYYY-MM.jsonl`) so "what did you do on the 14th" is a
  file lookup, and nothing is ever unlinked or overwritten.
  Correction on the record: an earlier claim in this file that v1 had *already*
  lost history to rotation was wrong. Verified on disk — `log.jsonl`
  (13 Jun → 28 Aug, 1.27 MB) and `log.jsonl.1` (14 May → 12 Jun, 580 MB,
  1.34M lines) are both intact; the record since 2026-05-14 is complete.
  `rotate_log()` keeps 3 generations and only runs at harness startup
  (`harness.py:1619`), which is how one generation reached 580 MB unchecked.
  Deferred follow-on: logs currently live in gitignored `.harness/`, so a dead
  laptop would take the trace with it — tracked as
  [issue #19](https://github.com/JanhaviDadhania/bismuth/issues/19), plus a
  per-event size cap, since with no rotation nothing else stops a runaway loop.

- **2026-08-28 — Pluggable components.** Janhavi: "we will design bismuth as
  components that can be plugged and unplugged." Every external seam sits
  behind a narrow interface with one implementation today and no assumptions
  leaking out: memory layer (git/GitHub), input transport (GitHub inbox repo),
  outbound channel (Telegram), STT (faster-whisper), TTS (macOS `say`).
  Why: it's what makes "for now it is GitHub, we'll change later" cheap instead
  of a rewrite. It's also why the speaker path can be added later without
  disturbing anything.

---

# The v2 architecture (Janhavi, voice note 2026-08-28)

Source: `~/Desktop/niulai.m4a`, transcribed via `tools/transcribe.py`. This is
the authoritative shape of v2. Everything above is detail feeding into it.

```
  push-button mic  ──►  STT  ──►  MAIN AGENT  ──►  spawns claude -p sub-agents
  (phone / laptop)       │         (thinks +          │
                         │          delegates          │
                         │          ONLY)              │
                         ▼             │               ▼
                       [log]        [log]           [log per sub-agent]
                                       │
                         ┌─────────────┴─────────────┐
                         ▼                           ▼
                    Telegram text/voice          Telegram media
                         │                           │  (links to images,
                       [log text,                  [log]   video, code,
                        not audio]                          long output)
```

**Input.** A push button with a microphone. Press, speak, release. No wake word
— "too messy". Laptop mic or phone mic; **mostly phone**. Press-and-hold vs
two-taps is negotiable; **the absence of a wake word is not**.

**Main agent.** Reads the instruction, decides what the subtasks are, writes
clear instructions for each, spawns `claude -p` sub-agents. It does **no work
itself**, deliberately: it must stay available because a second instruction may
arrive right after the first. It thinks and delegates. That is all it does.

**Output.** Telegram (Q7). Text and voice notes via `sendVoice`, media and
links via `sendPhoto`/`sendVideo`/`sendDocument`. Prompt rule from the voice
note still holds: don't emit 200–300 lines — write big things to a file, send
the link, summarise. Large artefacts get uploaded (e.g. to a GitHub repo) and
delivered as a link.
The **external speaker + TTS** path from the voice note is deferred, not
deleted — a second implementation of the same outbound seam.

**Trace (R4) — five logging points, all required:**
1. the STT transcript
2. the main agent's decomposition — what it split the task into
3. the instructions it sent to each sub-agent
4. what each sub-agent actually did
5. every reply sent to her, **as text only** (no audio files kept), including
   every media/link message

Content of the trace is **tool calls and whatever `claude -p` already emits,
nothing extra** — no reasoning capture, no decision notes. The stream-json
output *is* the trace.

## Major risks in this architecture (Bismuth, 2026-08-28)

1. **Voice-only output fails exactly when input succeeds.** Input is mobile;
   an external speaker is fixed to one room. *Resolved by Q7 — Telegram is the
   outbound channel, so replies follow her.*
2. **Press-and-hold doesn't exist on iPhone via Shortcuts.** Record Audio is
   tap-to-start / tap-to-stop, so the interaction is two taps unless a native
   app is built. *Accepted — either gesture is fine.*
3. **"Always available" is a property of the queue, not the agent.**
   `claude -p` exits per invocation and cannot accept instruction 2 while
   thinking about instruction 1. A disk spool is mandatory. *Understood and
   intended — a thin main agent keeps her wait short. Serialized, not batched
   (Q10).*
4. **Nothing verifies a sub-agent actually did the work.** She is told "done"
   on the sub-agent's own claim. **Accepted risk for v2** — tracked as
   [issue #18](https://github.com/JanhaviDadhania/bismuth/issues/18).
5. **Log retention.** *Resolved — no rotation, ever. See above.*
6. **Rate limits / cost can break the always-available promise.** Every note is
   one main-agent turn plus N sub-agents. *Accepted — if limits hit, messages
   wait in the queue.*

---

## Remaining open

- **Q8 — TTS voice.** Low priority. `tools/tts.py` (macOS `say`) generates the
  audio for Telegram `sendVoice`; `say` sounds like `say`, and a hosted TTS is
  a drop-in swap on the same seam. R2 fixed the STT engine, not TTS.
  *She'll decide the first time she hears it.*

- **Q12 — Cutover strategy.** *Resolved 2026-08-29: **hard cutover. v1
  stops.*** No parallel running, no two inboxes. Consequence to plan around:
  there will be a window with no working Bismuth, so v2's capture path should
  be built and proven before v1 is switched off.

- **Q13 — Refactor `harness.py` or write a new process?** *Reopened with new
  information 2026-08-29.* The original recommendation was refactor, because
  v1's harness already owned the hard parts. But Q14 just deleted watchers, the
  mailbox, the synthetic inbox, slash commands and coffeechat — several hundred
  lines of what made refactoring attractive. What v2 actually needs from v1 is
  narrow: the disk spool, `claude -p` invocation with resumable sessions,
  stream-json parsing, sub-process lifecycle with a concurrency cap and
  queueing, file locks, state persistence.
  Bismuth now recommends **a new, lean process that ports those specific pieces
  across**, rather than a refactor that starts by deleting half the file.
  *Status: awaiting Janhavi. Last question blocking the LLD.*

- **Q15 — Main agent session continuity.** *Resolved 2026-08-29:* one
  continuing session, **reset hard at 40% of the model's context window**.
  Automatic, no judgment. This differs from v1, which only *notified* the agent
  past `CONTEXT_ALERT_TOKENS = 120_000` and left the decision to it under
  protocol 04 — v2 replaces judgment with enforcement.
  Marked provisional by Janhavi: "it is a hard limit for now." Tracked as
  [issue #21](https://github.com/JanhaviDadhania/bismuth/issues/21) to tune the
  percentage from real usage data and consider a summarise-and-carry handoff so
  continuity survives a reset.
  LLD must define what the 40% is measured against, since 40% of 200k and 40%
  of 1M are very different amounts of conversation.

- **Q14 — What survives from v1's agent model.** *Resolved 2026-08-29:*
  **main agent + sub-agents only. Everything else is dropped.**
  - **coffeechat** — dropped. `prompts/coffeechat.md`, protocol 14, coffeechat
    session machinery all go.
  - **watchers** — dropped. `tools/watchers/` and the whole supervisor
    (`supervise_watchers`, `_spawn_watcher`, `kill_orphan_watchers`,
    `_notify_watcher_failure`) plus the synthetic inbox go.
  - **mailbox** — dropped. `read_mailbox` and the executor question/answer
    relay go.
  - **`/status` and `/halt`** — dropped. `status_report`, `handle_slash_command`
    and `halt_all` go.

  Consequences, recorded so they aren't a surprise later:
  1. **Nothing reaches Bismuth that Janhavi didn't say.** No 09:00 reminder
     surface, no dropbox folder pickup. `reminders.md` becomes a passive file
     she reads on the board or asks about.
  2. **A stuck sub-agent cannot ask a question.** It guesses or it fails.
     Combined with issue #18 (nothing verifies sub-agent work), both guards on
     that failure path are now off by choice.
  3. **No kill switch and no no-LLM introspection.** Stopping runaway work
     means killing the process by hand. The LLD should still expose *some*
     minimal way to see what's running and stop it.

  **This changes Q13.** Removing watchers, mailbox, synthetic inbox and slash
  commands strips several hundred lines out of what v2's harness needs to do.
  The refactor case weakens accordingly — see Q13.
