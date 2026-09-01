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

- **2026-08-28 — Transport: GitHub is the server.** ⚠️ **SUPERSEDED
  2026-08-31 — see the Telegram-input decision at the end of this log.** An iPhone client records
  audio and `PUT`s it to a private GitHub repo via the Contents API (one
  HTTPS call, no git on the phone, fine-grained PAT scoped to that one repo).
  Bismuth polls with an ETag every ~15s, downloads, runs it through the
  existing `tools/transcribe.py` path, processes it, then deletes the file.
  Why: GitHub is the durable buffer, so the Mac being asleep can't lose a
  note — the one job Telegram was really doing. No tunnel, no Tailscale,
  nothing listening on the Mac.

- **2026-08-28 — Delete from HEAD, keep the history.** ⚠️ **SUPERSEDED
  2026-08-31 (no GitHub inbox repo exists).** Processed notes are
  removed from HEAD only; the audio blobs stay in git history forever.
  Janhavi: "<1gb a year is nothing." No history truncation, no periodic
  re-init. Why: the history *is* the R4 input audit trail — every note you
  ever recorded, with a timestamp, permanently. Cost is ~1 MB/day.

- **2026-08-28 — ACK mechanism confirmed.** After processing, Bismuth writes
  `ack/<uuid>.json` back to the same repo — status, the memory path it landed
  in, and whether it's on the board. The client polls `ack/` and shows each
  note as **queued → uploaded → saved → on board**. Why: R3. Without an ACK
  she is trusting silence, which is the exact failure being fixed.

- **2026-08-28 — Local outbox queue confirmed.** ⚠️ **SUPERSEDED
  2026-08-31 (no phone-side client).** The client writes audio to a
  local outbox *before* attempting upload, and only deletes on a 2xx. Nothing
  is ever in flight without being on disk first. Why: R3 — a dropped note with
  no signal is the same failure as a dropped note in `dead_letter/`.

- **2026-08-28 — Sidecar metadata.** ⚠️ **SUPERSEDED 2026-08-31 — Telegram
  supplies the message date; no sidecar exists.** Each note ships a `.json` sidecar with
  `client_msg_id`, `recorded_at` (device local time + timezone) and duration.
  Why: commit time is when it *uploaded*; R4 wants when she *spoke*.

- **2026-08-28 — Outbox is local, not iCloud: `On My iPhone/Shortcuts/bismuth/outbox/`.**
  ⚠️ **SUPERSEDED 2026-08-31 (no phone-side client).**
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
  Shortcuts actions exist).** ⚠️ **SUPERSEDED 2026-08-31.** Record on phone → save to local outbox folder →
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

- **2026-08-31 — Input is Telegram. The iOS Shortcut and the GitHub inbox repo
  are dropped.** "let's keep telegram as audio input. I will speak to telegram
  only. no need for iphone shortcut." Telegram is now **both** the input and
  the output channel.
  Why it's the right call: Telegram's servers were already the durable buffer
  that the whole GitHub design existed to recreate. Dropping it removes the
  phone-side outbox, the drain loop, base64 encoding, the fine-grained PAT, the
  5-minute poll, the ack repo, *and* the one acknowledged hole in the design
  (notes stranded in an offline outbox). Nothing of ours runs on the phone.
  Given up: the permanent git-history archive of raw audio. Acceptable — the
  transcript is the R4 record and she has said she doesn't want audio kept.
  **What this makes load-bearing:** v1 lost 15 real messages on this exact
  transport (`dead_letter/`, 113 entries). v2's rule is that nothing is ever
  silently dead-lettered — failures go to a visible retry queue, she is told,
  and the count shows on the board.
  **Cutover consequence:** v1 and v2 cannot both poll `getUpdates` on one bot
  token — two consumers of one offset steal each other's messages. v2 gets a
  second bot token during development and is pointed at the real one at
  cutover.

- **2026-08-29 — Sub-agents do all memory writes.** Even a one-line append to
  `nexttodo.md` is delegated. The main agent's only outputs are sub-agent
  instructions and replies. Why: keeps the main agent's turn as short as
  possible, which is what availability costs. Accepted consequence: the ack is
  seconds rather than milliseconds.

- **2026-08-29 — Sub-agents are stripped bare.** No protocols, no skills, no
  `soul.md`, no identity — none of v1's `build_prompt` scaffolding. Consequence
  that is now a hard constraint: **every instruction the main agent writes must
  be self-contained** (absolute path, exact text, exact operation), because the
  sub-agent has no context to fall back on.

- **2026-08-29 — Session reset on request.** Beyond the automatic 40% reset,
  she can say "when you're done with this, reset the session". The reset is
  deferred until the current note is fully processed, then applied. A runtime
  instruction, not a slash command.

- **2026-08-29 — The trace schema is ours, not Claude's.** ⚠️ **SUPERSEDED
  2026-08-31 — see the fixed-stack decision below.** `subagent_event`
  normalises to `{tool, input, output, ok}` with `claude -p` stream-json as one
  *adapter*, raw line kept alongside. Why: R4 was defined as "whatever
  `claude -p` emits", which is a Claude-specific wire format — so model
  independence and R4 were on a collision course. This removes it.

## Q16 — Open-weight models for sub-agents

Raised by Janhavi 2026-08-29: "is it feasible to also create them from open
weight models? I am thinking to reduce dependency from claude."

Feasible, and sub-agents are the only good place for it — they are stateless,
single-purpose, and (since the bare-prompt ruling) receive fully self-contained
instructions, which is exactly the profile a smaller model can handle. The main
agent stays on Claude: it holds the session and makes the routing judgment.

Two real constraints: (a) the open-weight models genuinely good at multi-step
tool use are far too large for a laptop, so *local* means a small model that is
measurably worse at chained tool calls — hosted open-weight (Together /
Fireworks / Groq / OpenRouter) removes the Anthropic dependency without
hardware; (b) `claude -p` supplies the agent loop *and* the trace format, so a
non-Claude sub-agent means building both — hence the normalised trace schema
above, which must land first.

Suggested first trial: the note-writing sub-agent. Mechanical, and trivially
scoreable — did the right text land in the right file?

**Status: CLOSED 2026-08-31.** `claude -p` stays for both the main agent and
sub-agents. Not revisited in v2. See the fixed-stack decision below.

---

## Decisions — 2026-08-31

- **2026-08-31 — The stack is fixed. No pluggability layer.** Telegram in and
  out, faster-whisper for STT, macOS `say` for TTS, `claude -p` for the main
  agent and for sub-agents. No adapter interfaces, no registry, no config
  surface for swapping any of them. Janhavi: *"let's keep it simple. I will be
  using telegram for long. I will be using TTS AND STT model. It's not that
  difficult to change those. and claude -p will also stay same."* Why: an
  abstraction over one implementation costs an interface you must not leak
  through, a conformance suite, and a permanent lowest-common-denominator tax —
  paid for years to save a day of work that may never come. Supersedes the
  "pluggable components" design principle and the normalised-trace decision of
  2026-08-29. `subagent_event` now stores `claude -p`'s stream-json line as-is;
  the raw lines stay on disk, so any future reshaping is still possible.

- **2026-08-31 — The runtime owns its own durable queue.** Telegram holds
  messages too, but correctness does not depend on that. Janhavi: *"what if we
  include queue in our implementation?"* Why: no behavioural change — v2
  already spools to disk before advancing the offset — but it is now stated as
  a property of the runtime rather than a property borrowed from Telegram.

- **2026-08-31 — One voice: only the main agent talks to Janhavi.** Sub-agents
  have no Telegram channel at all — not for questions, not for progress, not
  for completion. Every message she receives was written by the main agent.
  Why: her explicit ruling, and it keeps the chat from reading like several
  programs talking over each other.

- **2026-08-31 — The main agent does no work whatsoever.** Not "writes nothing
  to memory" — *nothing*. No file edit, no command, no fetch, no search.
  Janhavi: *"main agent never does any work. if it needs to write something in
  file, it will be like, write 'this' in file. and sub agent will write it."*
  Enforcement is structural: **the main agent runs with no tools.** Why: a
  convention it is merely asked to respect will be broken on the turn where
  delegating feels slower than doing it.

- **2026-08-31 — Two task lists: `unclear` and `working`.** Ambiguous requests
  park in `unclear` *before* any question is asked, the main agent clarifies
  over Telegram, and only then does the task move to `working` and get broken
  into sub-agents. The task record holds each sub-agent's id and the verbatim
  instruction it was given. Why: park-first is the same rule as `others/` — a
  question that never gets answered must not be able to lose the request.

- **2026-08-31 — Sub-agent questions are a terminal status, not a channel.**
  A sub-agent ends as `done`, `needs_input`, or `failed`. On `needs_input` it
  **exits** carrying the question as its return value; the task moves back to
  `unclear` and the main agent asks her. Why: this gives back the ask-a-question
  loop she wants without reintroducing v1's mailbox — nothing is bidirectional
  and nothing sits running while a question waits. Closes the open
  "completion notification" item: the main agent relays completion, questions,
  and failures alike.

- **2026-08-31 — Sub-agent results feed the same serialized turn queue as
  notes.** A sub-agent finishing wakes the main agent exactly like an incoming
  note does; one queue, one turn at a time, in arrival order. Why: required,
  not optional — without it the `working → unclear` return path never fires
  until Janhavi happens to speak, and the loop deadlocks.

- **2026-08-31 — `tasks.json` is a projection of the trace, written by the
  runtime.** The main agent's turn returns *intents* (create / ask / clarify /
  spawn / done); the runtime performs them and writes a `task_*` trace event
  for each. Why: preserves the no-work rule above, keeps one source of truth
  (same pattern as the ack), and makes the task list rebuildable after any
  crash. It also makes the 40% session reset safe — the state was never inside
  the session.

- **2026-08-31 — Audio is kept forever, in a separate private repo.** Reverses
  the earlier "prune" recommendation. Every incoming voice note is archived to
  `bismuth-audio` as `<local ISO ts>__<trace_id>.ogg` under `YYYY/MM/`, joinable
  to the trace on `trace_id`. Janhavi: *"i want audio retained. setup a callback
  that keeps adding audios in seperate private repo."* Why a third repo, against
  the two-repo rule: audio is opaque binary bulk written on every note and read
  by nothing — in `bismuth-memory` it would grow that repo's history without
  bound and slow every sync of the thing that syncs constantly. Why the
  transcript alone is not enough: it is the only way to ever check whether
  faster-whisper heard her correctly.

- **2026-08-31 — Archiving is off the critical path.** Ingest *moves* staged
  audio into the archive working tree (a local rename, cannot fail on network)
  and returns; a background pusher commits and pushes on a timer. Two trace
  events, `audio_archived` and `audio_pushed`, because they fail independently.
  Why: **a note must never be blocked, delayed, or failed by the archive.** If
  GitHub is down for a day, a day of audio waits locally and the notes process
  normally.

- **2026-08-31 — `done` is an event, not a state; no cleanup daemon.** Folding
  a `task_done` event drops the task from the live list, so the list holds only
  `unclear` and `working`. Janhavi: *"if the task is done, we can remove it from
  the main agent's list. why bloat it. there could be a cleaning up demon
  running that does this. or something else. whichever is best architecture
  wise."* Why not a daemon: because `tasks.json` is a projection, nothing
  accumulates to sweep — a daemon would be another process to supervise, could
  race with a turn in flight, and would exist only to delete state we never
  needed to keep. Nothing is lost; every task ever created stays in the trace.
  One concession: a five-line tail of recently-done tasks is injected into the
  turn so *"change that thing you just did"* has something to bind to.

- **2026-08-31 — Board gets a `Tasks` section in the main space; acks go to a
  secondary strip.** `Tasks` is a top-level section peer to projects,
  miniprojects and reminders, showing `NEEDS YOU` (with count) above `WORKING`.
  Acks and recently-completed tasks move to a strip at the foot of the board.
  Janhavi: *"i liked the idea of showing main agent's list on board... we can
  show ack on board but keep is somewhere not occupying the main space."* Why:
  the main space belongs to live work and to anything waiting on *her*; an ack
  is reassurance she goes looking for, not information to push at her. This is
  an explicit amendment to R1, which had frozen the board's design — it adds
  sections, and changes nothing that already renders.

- **2026-08-31 — Every trace event carries `ts`, `seq` and `trace_id`.**
  `seq` is a global, gapless, monotonic integer assigned under the append lock,
  and it — not `ts` — is the authoritative sort key. Janhavi: *"i hope all
  events in trace are saved with time so i can sort on it and see what happened
  in what order. I need a complete trace."* Why `ts` alone is insufficient: a
  turn can spawn four sub-agents inside one millisecond, and timestamps with
  different UTC offsets (travel, DST) do not sort lexicographically. Bonus
  property: **a gap in `seq` means an event was lost**, so trace completeness
  becomes checkable rather than assumed.

- **2026-08-31 — Capture `claude -p` stream-json for the main agent too, not
  just sub-agents.** New events `agent_event` and `turn_usage`. Janhavi asked
  whether this is costless. Answer, recorded so it is not re-litigated:
  **token cost is genuinely zero** — the stream is the model's own output
  re-rendered, no extra calls, no extra tokens. **Disk cost is not zero** and is
  the largest driver of trace size, since one tool result can be a whole file
  read; the per-event size cap is what holds it. **What it contains:** every
  assistant message, every tool call with full input, every tool result, and a
  final `result` message with token usage. **What it does not contain:** the
  model's reasoning — it is a complete record of *what was done*, not *why it
  was decided*. Useful side effect: the `result` message's usage numbers turn
  the 40% session-reset rule from an estimate into an exact measurement, closing
  the "what is the 40% measured against" gap.

- **2026-08-31 — Runtime state is tiered, not one dictionary.** Answering
  *"is there a dictionary somewhere in code that has all that?"*: **tier 1**
  (`~/.bismuth/state.json`) is authoritative and small — `offset`,
  `processed_ids`, `turn_queue`, `session`. **Tier 2** (`tasks.json`,
  `subagents.json`) is derived, folded from the trace at boot, and can be
  deleted without loss. **Tier 3** is ephemeral and dies with the process.
  Why it matters beyond tidiness: it makes **boot reconciliation** expressible —
  a sub-agent with a `subagent_spawned` event and no terminal event was killed
  by the crash, so it is marked failed and its task returns to `unclear` and she
  is told. With one flat dictionary there is no way to distinguish "is running"
  from "was running before we died", which is precisely how v1 accumulated 113
  dead-lettered entries nobody was ever told about. `turn_queue` is the only
  state with no rebuild path, so it is written before a sub-agent is reaped.

- **2026-08-31 — Thinking stays on; sub-agents use `--effort low`, never
  thinking-disabled.** Janhavi asked whether capturing the agent's thinking
  costs tokens. Recorded so it is not re-litigated: **yes — thinking tokens are
  billed as output tokens.** But three measured facts change the decision.
  (a) On Opus 5 adaptive thinking is **on by default**, so this was never an
  opt-in cost; and it spends nothing when unused — probes returned
  `output_tokens_details.thinking_tokens: 0` on trivial prompts. (b) `claude -p`
  reports that field in its `result` event, so v2 gets exact per-turn thinking
  spend in the trace for free. (c) *Seeing* it is free — the thinking is already
  billed, and display settings do not change billing; what is unavailable is the
  raw chain of thought, which Opus 5 never returns (summaries only).
  **The load-bearing part:** disabling thinking on Opus 5 has a documented
  failure mode where the model writes a tool call into visible text instead of
  emitting a real one — the turn succeeds, the work never happens, no error is
  raised. For a sub-agent whose whole job is one file append, that manufactures
  issue #18 ("sub-agent silently does nothing") in a system with no verification
  to catch it. Low effort gets the saving without buying the failure. The real
  cost of thinking is the **context window**, which drives the 40% reset harder.

- **2026-08-31 — For tracing *why*, a stated reason beats captured thinking.**
  The main agent returns a one-line reason with its routing intent, recorded in
  `route_decided`. Why: it is a handful of tokens, structured, and — the part
  that matters — a **commitment attached to the action**. Thinking explores
  options the model then abandons, so as an R4 audit record it can actively
  mislead about why something happened.

- **2026-08-31 — Strip the `claude -p` prefix. Measured, not estimated.**
  Janhavi: *"we will work on remove claude's own prompt 26k tokens. I am sure I
  don't need that hell."* A default spawn carries **27,398 tokens** before the
  instruction is read. Decomposition: irreducible wrapper **805** (cannot be
  removed), Claude Code's own system prompt **3,021**, built-in tool schemas
  **14,749**, skills **5,310**, MCP **1,975**, CLAUDE.md/cwd the remainder.
  **Tool schemas are more than half** — the opposite of where the earlier draft
  looked, which had assumed the *instruction* was the expensive part. Stripped
  config measures **3,355 tokens: an 87.7% reduction.** This supersedes the
  claim in the architecture doc that bare prompts make sub-agents cheap; what
  bare prompts actually buy is the *ability* to strip the runner.

- **2026-08-31 — Sub-agent tool set is exactly `Read,Write,Edit,Bash`.**
  Janhavi: *"I just need terminal tool and browser and that's it. browser is
  silicon browser."* Read/Write/Edit are the memory writes. Bash is the
  terminal. **The browser needs no tool and no MCP server**: `silicon` is a CLI
  at `~/.local/bin/silicon` (`silicon browser [name]`), so Bash already reaches
  it — the one capability that looked like it needed an MCP server turned out
  to be a command. Per-tool schema cost above the 805 floor: Edit 348,
  Write 522, Read 608, Bash 1,358. Bash is the most expensive of the four and
  the one that lets a sub-agent wander; kept deliberately, with the cost
  recorded rather than argued.

- **2026-08-31 — No skills, no MCP, own system prompt.** Janhavi: *"i don't
  need any skill... remove useless MCP servers... we will replace system prompt
  with our prompt."* `--disable-slash-commands`, `--strict-mcp-config` with no
  `--mcp-config` (dropping all ~30 servers inherited from the work `claude.ai`
  account — they cost only ~2k today only because every one reports "needs
  authentication" and never loads its schemas; authenticate one and that climbs),
  and `--system-prompt` to replace Claude Code's 3,021-token prompt outright —
  not `--append-system-prompt`, which keeps it.

- **2026-08-31 — Cutting tools removes expensive *paths*, not just prefix.**
  The stronger reason for the short tool list, measured on a real one-line file
  append: a default-configured spawn reached **118,011 tokens / $0.37** because
  it had the full tool set and chose to shell out through Bash three times, each
  command's output re-entering context. The stripped config used `Read` then
  `Edit` for **8,092 tokens / $0.024** — 15× cheaper, correct both times, and it
  obeyed the terse-reply instruction. Single run each; treat costs as
  directional.

- **2026-08-31 — Main agent runs `--tools ""` and returns intents as JSON.**
  Its no-work ruling makes it the cheapest process in v2: **805 tokens plus her
  prompt**. `claude -p --json-schema` validates structured output, so the
  create/ask/clarify/spawn/done intents come back as validated JSON rather than
  prose the runtime parses hopefully. *Open: the intent schema is not yet
  written.*

- **2026-08-31 — Stripping breaks per-folder `CLAUDE.md`; repair is explicit.**
  `~/bismuth-memory` has **5 `CLAUDE.md` files** (~10.6 KB) under
  `siliconResearch`, `find_a_job/star`, `find_a_job/amp`,
  `nostayidiot/twitterdaily`, `find_a_job/sarvam/outreach` — the deliberate
  "each folder's context lives beside its data" rule. A stripped sub-agent in a
  clean cwd does not auto-discover them. Fix: **the main agent names the
  `CLAUDE.md` path in the instruction** (the sub-agent has Read) or inlines the
  relevant lines. Why this is better than what it replaces: it converts implicit
  discovery into an explicit step that lands in the trace, and it is what the
  self-contained-instruction rule already required.

- **2026-08-31 — `--bare` cannot be used; `< /dev/null` is required.**
  `--bare` skips hooks, LSP, plugin sync and CLAUDE.md discovery — but refuses
  OAuth and the keychain and demands `ANTHROPIC_API_KEY`; on Janhavi's
  subscription login it returns *"Not logged in · Please run /login"*, so using
  it would mean paying API rates separately from the subscription. Separately,
  every spawn without `< /dev/null` stalls **3 seconds** waiting on stdin —
  pure added latency on her ack, on every sub-agent.

- **2026-08-31 — `--max-budget-usd` per spawn.** Partly closes the "runaway
  work, no kill switch" gap in §7 of the architecture: not a kill switch for the
  main agent, but a hard bound on the blast radius of a runaway sub-agent — the
  failure the 118k-token spawn above demonstrates is real.

- **2026-08-31 — Correction: the stripped figures are *carrier cost*, not
  totals.** Janhavi caught that the measurements used `--system-prompt "x"`, a
  one-character placeholder, because the real prompt is not written yet. So
  3,355 (sub-agent) and 805 (main agent) are what a spawn costs **before** her
  prompt. Measured with v1's prompts as anchors: sub-agent carrier 3,355 →
  **3,858** with `executor.md` (prompt costs 503); main agent carrier 805 →
  **2,523** with `assistant.md` (prompt costs 1,718). The like-for-like
  reduction is therefore **27,398 → 3,858 = 85.9%**, not the 87.7% recorded
  earlier — the default baseline includes Claude Code's own 3,021-token system
  prompt, so comparing it against a one-character placeholder flattered the
  result by ~3k. Useful consequence: replacing Claude's prompt is a swap with a
  **3,021-token budget** before it costs anything, and `executor.md` spends only
  17% of it — so there is no reason to write the v2 prompts tersely. Planning
  ratio for her markdown: **~2.8 bytes per token**, not 4.

## Decisions — 2026-08-31 (writing the prompts)

- **2026-08-31 — v2's scope is capture and retrieval. The brainstorming
  partner moves out of Bismuth.** Janhavi: *"earlier bismuth, v1, was an
  assistant, a brainstorming partner and worker too. this new bismuth is mainly
  an agent that listens to me and puts things in memory without ever missing.
  second, it can search in unstructured memory when i ask for something. this is
  scoped down version. I will be moving out the brainstorming agent from
  bismuth."* Two jobs, and only two: **nothing she says is lost**, and **she can
  get it back**. Consequences: (a) `assistant.md`'s companion half — mood
  reading, register matching, Rogers / MI / Linehan / Stern / Hakomi, "amplify
  her vibe" — is **not carried into v2**; what survives is tone only (plain,
  short, congruent, no flattery). (b) The main agent is told explicitly not to
  join in when she thinks out loud — capture it and stay out of the way. (c)
  **Retrieval is a first-class job**, not an afterthought, and it needed
  designing: see the search decisions below.

- **2026-08-31 — Both prompts are written**, at `prompts/v2/main_agent.md` and
  `prompts/v2/subagent.md`. This closes the blocking item in §9 of the
  architecture. Measured cost, same method as the stripping measurements
  (placeholder `--system-prompt "x"` for the carrier, then the real file):

  | | carrier | with real prompt | prompt costs |
  |---|---:|---:|---:|
  | Main agent, `--tools ""` | 805 | **4,779** | 3,974 |
  | Sub-agent, `Read,Write,Edit,Bash` | 3,355 | **5,063** | 1,708 |

  Both carriers reproduced the previously recorded figures exactly, which is a
  useful check on the earlier measurement. Like-for-like against the 27,398
  default spawn, the sub-agent is an **81.5% reduction**. The sub-agent prompt
  spends **57% of the 3,021-token swap budget**; the main agent prompt
  **exceeds it by 953** — noted rather than trimmed, because the budget is the
  cost of a *swap* and Claude Code's own prompt does none of this job. Actual
  bytes-per-token for these files: **2.89**, close to the 2.8 planning ratio.

- **2026-08-31 — The intent schema is written**, at
  `prompts/v2/intent_schema.json`. Shape: `{"intents": [ … ]}`, performed by the
  runtime in listed order; an empty list means silence. Eight types: `route`,
  `task_create`, `task_ask`, `task_clarify`, `spawn`, `task_done`, `reply`,
  `session_reset`. **Flat object, not `oneOf` per type** — every intent is one
  object with `type` plus optional fields, `additionalProperties: false`, and
  the per-type required fields documented in the prompt rather than in the
  schema. Why: structured-output validators handle discriminated unions
  inconsistently, and a schema that `--json-schema` rejects at runtime is worse
  than one that under-constrains. The prompt carries the strictness.
  `task_ref` is either an existing `task_id` or a short label invented for a
  task created in the same turn, which the runtime maps — needed because the
  agent cannot know an id the runtime has not assigned yet.

- **2026-08-31 — The sub-agent's return shape is a JSON final message**, at
  `prompts/v2/subagent_result_schema.json`: `status` (`done` / `needs_input` /
  `failed`), `summary`, `output`, `question`, `error`. Why a JSON object rather
  than `--json-schema` on the spawn: the sub-agent runs *with* tools, and that
  flag combination is untested here; the prompt requires the shape and the
  runtime parses it, marking anything unparseable as `failed` — which is
  visible, not silent.

- **2026-08-31 — The main agent receives a `DESTINATIONS` block every turn.**
  This closes a real hole: the main agent runs `--tools ""`, so *it cannot
  check whether a path exists*, yet §4.6 requires that the destination already
  exist. The runtime injects the current memory tree — paths, plus which folders
  carry a `CLAUDE.md` — alongside `NOTE`, `TASKS`, `RECENT` and `OTHERS`. The
  agent may route only to something in that block, or to `others/`. The
  `CLAUDE.md` flag is what lets it satisfy the §4.9.1 repair without guessing.

- **2026-08-31 — Retrieval is a task, with `kind: "search"`.** Not a special
  path: she asks a question about her own memory, the main agent creates a task,
  spawns a read-only worker with an explicit search instruction (which subtrees,
  which terms and misspellings, return matching lines *with paths*), and answers
  her from the result in its own words. Questions about *what happened* rather
  than what she wrote are answered from **the trace**, not the memory tree.
  Why a task and not a shortcut: it shows up in `WORKING` on the board, so she
  can see it is looking, and `done` drops it like any other task.

- **2026-08-31 — The anti-fabrication rule, stated in both prompts.** The
  sub-agent must never invent a path, filename or quote, and an empty result is
  a correct answer. The main agent must never claim something is saved before a
  worker reports it saved, and must never answer from "memory" — it has none
  beyond the current turn. Why it earns the tokens: retrieval is the one job
  where a confident wrong answer is worse than no answer, and issue #18 means
  nothing downstream will catch it.

- **2026-08-31 — Sub-agents read back what they wrote.** After any write or
  edit, re-read the changed region and confirm the text is there before
  reporting `done`. Why: it does not close issue #18 — nothing independently
  verifies a sub-agent — but it converts the specific failure the system is most
  exposed to (a model that reports success without having written anything) from
  undetectable into self-detectable, for a few hundred tokens.

- **2026-08-31 — Sub-agent effort posture: retry the mechanism, never
  reinterpret the task.** v1's `executor.md` said *"don't bail on the first
  wall"*; v2 says *"do exactly the instruction, nothing more."* These conflict
  without a rule, so: a missing directory, permission, wrong flag or transient
  failure is a **mechanism** problem — find another way. What was asked is the
  **task** — never re-scope it, never substitute a different file, never decide
  the request was mistaken. If the task itself cannot be done as written, end
  `failed` or `needs_input`.

- **2026-08-31 — The runtime owns git for `bismuth-memory`; sub-agents never
  run it.** The sub-agent prompt forbids `git` outright. Why: several workers
  can run concurrently, and a commit from inside one of them races the others
  and the sync loop. Same shape as the audio pusher — a background loop, off the
  critical path, honouring the existing commit-and-push-before-pull rule that a
  single-shot worker cannot.

- **2026-08-31 — Two operational rules the sub-agent prompt states explicitly,
  because they are silent killers.** (a) **Nothing interactive** — spawns run
  with no stdin, so `git commit` without `-m`, a pager, or any prompt hangs the
  worker until it is killed. (b) **Absolute paths always** — a stripped worker
  starts in a directory it knows nothing about.

## Decisions — 2026-08-31 (building the runtime)

Decisions forced by the implementation, all measured or exercised rather than
assumed. The code is `v2/`, tests are `tests/test_v2.py`.

- **2026-08-31 — Sub-agent spawns need `--permission-mode bypassPermissions`.**
  Not in §4.9.1's spawn command, and it must be: in print mode a tool call that
  needs permission is *denied*, so a worker whose whole job is a file write
  fails every time. Verified by running one: without it, nothing is written.

- **2026-08-31 — `DESTINATIONS` is injected once per session, not per turn.**
  Measured on her real tree: the block is **~3.2k tokens** (244 folders). Per
  turn that would dominate the context and drive the 40% reset several times
  faster. So it is sent on the first turn of a session and again only when the
  tree's fingerprint changes, and the runtime tells the agent it is a
  replacement. Filenames are included rather than folder names alone — that
  costs ~1.3k of the 3.2k and is worth it: without them the agent guesses
  `nexttodo.md` against a real `next_todo.md`, the worker dutifully creates the
  wrong file, and her notes silently split. That is the exact failure R3 exists
  to prevent. `_archive/` is excluded from routing destinations.

- **2026-08-31 — The runtime writes `others/` itself, not a sub-agent.**
  Park-first has to be atomic. If parking were delegated, a worker failure
  would lose the note in the window between "we couldn't route it" and "it is
  on disk" — the one thing §4.7 exists to prevent. The runtime writes
  `others/<timestamp>__<trace_id>__<slug>.md` synchronously, then the question
  is asked. Tested: `test_park_writes_before_the_question_is_asked` asserts the
  trace ordering, not just the outcome.

- **2026-08-31 — Consequence: the agent does not know the `others/` filename.**
  It named one in testing and was wrong, which is a trust bug however small.
  The prompt now says the runtime names the file and the `OTHERS` block will
  show it next turn — never state a filename you have not been shown.

- **2026-08-31 — The routing guard is enforced in the runtime, not trusted to
  the prompt.** If the agent names a destination that does not resolve, the
  runtime does *not* write it: it emits `route_rejected`, parks the note in
  `others/`, and records why. So "the destination must already exist" is a
  property of the system rather than an instruction the model might miss.

- **2026-08-31 — A successful note-filing worker does not wake the main agent.**
  Sub-agent results feed the turn queue (§4.8), but a plain `route` write that
  returned `done` gives the agent nothing to decide, and a turn per note would
  cost ~$0.08 and delay her next note for nothing. So the queue is woken when
  `status != done` **or** the worker belongs to a task. Everything that needs
  judgement still reaches the agent; the ack is written by the runtime either
  way.

- **2026-08-31 — Route workers are tracked in the projection like any other.**
  Otherwise a crash mid-write leaves no `running` record for boot reconciliation
  to find, and the note goes quiet — which is v1's failure mode exactly.

- **2026-08-31 — Sub-agent results are written to the queue before the worker
  thread ends**, per §6's rule that the write is the commit point.

- **2026-08-31 — The board additions are a guarded import.** `tools/board.py`
  gains three sections via `v2/board_sections.py` inside a `try/except`, so the
  board renders exactly as before if v2 is absent or misconfigured. R1 said
  don't redesign the board; this adds and changes nothing that already rendered.

- **2026-08-31 — `python3 -m v2 feed "<text>"` is the offline test path.** Runs
  one note through the real agents with real workers, prints her side instead of
  sending it, and drains sub-agent results to settlement. With `BISMUTH2_*`
  pointed at a scratch tree, nothing rehearses against her real memory.

- **2026-08-31 — Measured cost of one note, end to end.** Main agent turn
  **$0.079** (7,018 tokens of context — 3.5% of a 200k window, so ~28 notes to
  the 40% reset), plus one sub-agent at **$0.044**. About **$0.12 a note**. The
  earlier 8,092-token figure for a file append was optimistic in practice: the
  real worker spent 22,957, mostly because it chose `Bash` (`od`) for its
  read-back verification rather than `Read`.

- **2026-08-31 — Exercised end to end before declaring it done**, against a
  scratch memory tree: declared routing, mangled-STT recovery ("sheldon" →
  `projects/seldon/`), an unroutable note parking in `others/` and asking her,
  her answer draining it into a folder created after the session started, a
  full task lifecycle with `task_done`, and a retrieval query answered with the
  quoted line and its path. All traced, all ordered, no gaps.

## Decisions — 2026-09-01

- **2026-09-01 — v2 runs on v1's bot. The §11 second-token rule was the wrong
  guard.** §11 said build against a second bot token because v1 and v2 cannot
  both long-poll `getUpdates` at once, and `config.check()` enforced that by
  refusing v1's token outright. That is the wrong test: what breaks is two
  *processes* polling one token, not which token v2 holds. The v1 harness was
  already stopped, so the constraint did not apply. `check()` now blocks only
  when `harness.py` is actually running (`pgrep`), and otherwise allows the
  reuse. Effect: the §11 step-10 cutover happened early and for free, because
  there was nothing left to cut over from. Bot is `budee123bot`; the token
  lives in `config.yaml`, which is gitignored.

- **2026-09-01 — Issue #19 closed itself.** The trace lives at
  `~/bismuth-memory/trace/`, so the runtime's own git loop commits and pushes
  it — first observed at `86a1c4f`. The deferred "move the trace under version
  control so it is genuinely permanent" item needed no work; it fell out of
  putting the trace inside the memory repo.

- **2026-09-01 — `~/bismuth-audio` initialised locally, with no remote.**
  Voice notes archive into `YYYY/MM/` immediately; pushes are traced no-ops
  until a private GitHub repo exists and `origin` is set. This is the intended
  degradation, not a gap: archiving is off the critical path, so a note is
  never blocked, delayed or failed by the archive.
