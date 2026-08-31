# Bismuth v2 — Architecture

Status: **draft for Janhavi's review.** No code has been written.
**Both prompts are now written** — `prompts/v2/main_agent.md` and
`prompts/v2/subagent.md`, with `intent_schema.json` and
`subagent_result_schema.json` beside them (§10). After the runtime stripping in
§4.9.1 they are the only behavioural content in v2.
**Next action: build, in the order of §11.**
Companion doc: `docs/V2_REQUIREMENTS.md` — requirements, and the dated decision
log every choice here traces back to.

This document describes *what v2 is*, component by component, plus the exact
life of a single voice note from her mouth to the board. Where a design choice
is still open, it is marked **OPEN** inline rather than silently assumed.

---

## 1. What v2 is

One sentence: **Janhavi speaks into her phone, and a thing she trusts puts it
in the right place, tells her it did, and can find it again when she asks.**

Everything else — sub-agents, tracing, the board — exists to make that sentence
true and verifiable.

**v2 is a scoped-down Bismuth.** *Ruled 2026-08-31.* v1 was three things: an
assistant, a brainstorming partner, and a worker. v2 is **capture and
retrieval, and nothing else** — it listens without ever missing, and it searches
her unstructured memory when she asks. The brainstorming partner is moving out
of Bismuth entirely. This is why `assistant.md`'s companion half does not appear
in the v2 main agent prompt: the job it served is no longer this system's job.

### The four requirements this serves

- **R1 — the board.** Accepted as-is. v2 feeds it; v2 does not redesign it.
- **R2 — STT.** Accepted as-is. faster-whisper via `tools/transcribe.py`.
- **R3 — no clutter, and trust.** 100% confidence that what she says is saved
  in the right place and appears on the board. This is the load-bearing one.
- **R4 — complete tracing.** Everything Bismuth did, with dates and times,
  permanently.

### The design principle underneath

**As small as it can be, and one voice.** *Ruled 2026-08-31.* The stack is
fixed and named: Telegram in and out, faster-whisper for STT, macOS `say` for
TTS, `claude -p` for the main agent and for sub-agents. There is no adapter
layer, no registry, no configuration surface for swapping any of them. Each
sits behind a plain function call, and if one is ever replaced, replacing it is
a day of work — which is cheaper than carrying an abstraction for years to save
that day.

Three things *are* structural, and the rest of this document is about them:

- **One voice.** Only the main agent talks to Janhavi. Sub-agents never do —
  not for questions, not for progress, not for completion (§4.8).
- **One queue.** The runtime owns a durable spool of its own. Telegram happens
  to hold messages too, but correctness does not depend on that (§4.2).
- **One record.** The trace is the single source of truth. The board and the
  task list are both projections of it — never separate files that can drift.

---

## 2. System overview

```
  ┌──────────────┐
  │   iPhone     │  record a voice note in Telegram, send to the bot
  │  (Telegram)  │
  └──────┬───────┘
         │  getUpdates long-poll, persisted offset
         ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │                     THE RUNTIME (laptop)                        │
  │                                                                 │
  │   ingest ──► STT ──►┌───────────┐                               │
  │                     │ TURN QUEUE│◄──────────────────┐           │
  │                     └─────┬─────┘   sub-agent       │           │
  │                           │         results         │           │
  │                           ▼                         │           │
  │                    ┌─────────────┐                  │           │
  │                    │ MAIN AGENT  │  one session     │           │
  │                    │  NO TOOLS   │  one turn        │           │
  │                    └──┬───┬───┬──┘  does no work    │           │
  │                       │   │   │                     │           │
  │        ┌──────────────┘   │   └──────────┐          │           │
  │        ▼                  ▼              ▼          │           │
  │   ┌─────────┐       ┌──────────┐   ┌──────────┐     │           │
  │   │  reply  │       │TASK LIST │   │SUB-AGENTS│─────┘           │
  │   │ to her  │       │ unclear  │   │(claude -p│                 │
  │   └────┬────┘       │ working  │   │ bare, no │                 │
  │        │            └────┬─────┘   │ voice)   │                 │
  │        │                 │         └────┬─────┘                 │
  │        │                 │              │ all writes            │
  │   ═════╪═════════════════╪══════════════╪═══════════════════    │
  │        │   TRACE (append-only, never rotated) — the record      │
  └────────┼─────────────────┼──────────────┼────────────────────---┘
           ▼                 ▼              ▼
   ┌───────────────┐   ┌──────────┐  ┌──────────────────┐
   │   Telegram    │   │  board   │  │  bismuth-memory  │
   │ text · voice  │◄──│  .html   │◄─│  markdown files  │
   │ image · video │   └──────────┘  └──────────────────┘
   └───────────────┘
```

One channel in, one channel out, and they are the same channel — and only the
main agent is ever on it. Sub-agents touch memory and nothing else; the board
and the task list are both read out of the trace.

---

## 3. Components

No abstraction layers. Each component is the concrete thing named.

| # | Component | What it is |
|---|-----------|------------|
| 1 | Capture client | Telegram app on her phone — nothing of ours runs there |
| 2 | Transport | Telegram Bot API, inbound and outbound, one bot |
| 3 | Ingest | `getUpdates` long-poll → disk spool → advance offset |
| 4 | STT | `tools/transcribe.py`, faster-whisper `base`, as a subprocess |
| 5 | Turn queue | one serialized queue: notes **and** sub-agent results (§4.8) |
| 6 | Main agent | `claude -p`, one session, one turn at a time, `--tools ""` |
| 7 | Task list | the main agent's `unclear` / `working` bookkeeping (§4.8) |
| 8 | Sub-agents | `claude -p` subprocesses, stripped runner, `Read/Write/Edit/Bash` (§4.9.1) |
| 9 | Memory | markdown in git at `~/bismuth-memory` |
| 10 | TTS | `tools/tts.py`, macOS `say`, as a subprocess |
| 11 | Trace | append-only JSONL, never rotated, `seq`-ordered |
| 12 | Audio archive | `bismuth-audio` — separate private repo, kept forever (§4.1) |
| 13 | Board | `tools/board.py` → `board.html` |

---

## 4. The life of one voice note

The normative walkthrough. Every numbered step is also a trace event.

### 4.1 Capture (Telegram)

1. She records a voice note in Telegram and sends it to the bot. **No wake
   word.** No app of ours on the phone, no Shortcut, no outbox, no token on the
   device, nothing to install or maintain.
2. Telegram's servers hold the message until the runtime asks for it.

**Telegram is the durable buffer.** This is the job GitHub was brought in to
do, and Telegram was doing it for free the whole time: the note is safe the
moment it sends, whether or not the laptop is awake, on wifi, or alive. The
phone-side outbox, the retry loop, the base64 encoding, the fine-grained PAT
and the offline-queue hole all disappear along with the Shortcut, because
Telegram's own client already solves them.

**Audio is kept forever.** *Ruled 2026-08-31 — reverses the earlier "prune"
recommendation.* Every incoming voice note is archived to a **separate private
repo**, `bismuth-audio`, and never deleted. The transcript is the searchable R4
record; the audio is the ground truth behind it, and the only way to ever check
whether faster-whisper heard her correctly.

**Layout — sortable, and joinable to the trace:**

```
bismuth-audio/
  2026/
    08/
      20260831T143041+0530__upd_884213.ogg
      20260831T151202+0530__upd_884219.ogg
```

Filename is `<local ISO timestamp>__<trace_id>`, so the directory sorts
chronologically on its own and every file joins to its `note_received`,
`stt_done` and `ack` events on `trace_id`. Year/month directories keep any
single directory small.

**Archiving is off the critical path.** *This is the load-bearing design
choice.* Ingest **moves** the staged audio into the archive working tree and
returns immediately — that is a local rename, it cannot fail on network. A
separate **archive pusher** commits and pushes on a timer, batching whatever
has accumulated. A push that fails is retried on the next tick and the note is
completely unaffected, because it was already processed.

The rule that follows: **a note is never blocked, delayed, or failed by the
archive.** If GitHub is down for a day, a day of audio sits in the local
working tree and pushes when it returns. Trace: `audio_archived` on the local
move, `audio_pushed` on the successful push — two events, because they are two
independently-failing things.

**Why a third repo and not `bismuth-memory/`.** The two-repo rule stands for
*code and notes*; this is neither. Audio is opaque binary bulk, it is written
on every single note, and it is never read by anything. Putting it in
`bismuth-memory` would grow that repo's history without bound and slow every
clone and every sync of the thing that syncs constantly. A separate repo keeps
the bulk where nothing has to walk past it.

**Size, honestly.** Telegram voice notes are Opus, roughly 1 KB/second. Even at
50 notes a day averaging 30 seconds, that is ~1.5 MB/day — well under a
gigabyte a year, matching her earlier "<1 GB a year is nothing." Revisit only
if the repo passes ~2 GB, at which point yearly repo rotation is the simple
answer.

### 4.2 Ingest

3. `getUpdates` with a persisted offset, **long-polled**. Telegram holds the
   connection open until something arrives, so pickup is near-instant and costs
   nothing — no rate-limit budget to manage, no polling interval to tune.

> **OPEN — pickup cadence.** The 5-minute interval was a concession to
> GitHub's rate limits and has no reason to exist on Telegram.
> **Recommendation: long-poll**, i.e. effectively instant, which is also what
> v1 already does. Confirm, since the 5-minute instruction predates this change.

4. For each voice or audio message: `getFile`, then download to local staging.
5. **Spool to disk before advancing the offset.** The offset is the commit
   point — it moves only after the message is durably on disk. A crash before
   that means Telegram serves the message again on restart.
6. A dedup ledger keyed on Telegram's `update_id` makes redelivery a no-op.
   Trace: `note_received`.

**The failure this must not repeat.** v1 ran on exactly this path and lost
messages. `~/bismuth-memory/.harness/dead_letter/` holds **113 entries** — 15
of them real messages from her, including *"can you hear me?"* from 13 June —
and nothing ever told her they had been dropped.

So the v2 rule, and it is the crux of R3 now that the transport is Telegram
again: **nothing is ever silently dead-lettered.** A batch that fails
processing goes to a visible retry queue, she is told about it over Telegram,
and the count is rendered on the board. A message may fail; it may not fail
quietly.

### 4.4 Transcription

8. Run `tools/transcribe.py` as a subprocess so the whisper model never lives
   inside the runtime process. Trace: `stt_done` with the transcript.

R2 fixes this component and v2 does not revisit it.

If STT fails: the offset is **not** advanced past the message, the ack records
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

**The 40% is measured against real numbers, not an estimate.** `claude -p`'s
final `result` message reports actual token usage for the turn (§5), so the
runtime knows the true running context size rather than guessing from
characters. The window it is 40% *of* is the configured model's context length,
recorded in the trace at session start so a reset is always explainable after
the fact.

**Thinking stays on, everywhere.** *Ruled 2026-08-31.* Thinking tokens are
billed as output tokens, so they are not free — but on Opus 5 adaptive thinking
is **on by default and costs nothing when it is not used**: measured
`output_tokens_details.thinking_tokens` was `0` on trivial prompts. `claude -p`
reports that field in its `result` event, so v2 gets exact per-turn thinking
spend in the trace for free, and can measure rather than guess.

**Sub-agents run `--effort low`, not thinking-disabled**, and the distinction
is load-bearing. Disabling thinking on Opus 5 has a documented failure mode
where the model writes a tool call into its *visible text* instead of emitting
a real tool call: **the turn succeeds, the write never happens, and no error is
raised.** For a sub-agent whose entire job is one file append, that is issue
#18 — "sub-agent silently does nothing" — manufactured on purpose, in a system
that has no verification to catch it. Low effort gets the cost saving without
buying that failure.

The real cost of thinking here is not the bill, it is the **context window**:
thinking consumes it, which drives the 40% session reset more often.

**Its job is to think and delegate, and stay available.** It must not tie
itself up doing work, because a second note may arrive seconds later. Her wait
is exactly the main agent's turn length, so the turn is kept short by design.

**The main agent does no work at all.** *Ruled 2026-08-29, restated absolutely
2026-08-31.* Not "writes nothing to memory" — **nothing**. It does not edit a
file, run a command, fetch a page, or search a directory. Even a one-line
append to `nexttodo.md` is delegated: the main agent's output is the sentence
*"append this exact text to this exact path"*, and a sub-agent is what touches
the disk.

Its only three outputs are:

1. **sub-agent instructions** — the work, spelled out;
2. **task-list intents** — *create*, *ask*, *clarify*, *spawn*, *done* (§4.8);
3. **replies to her** over Telegram.

Concretely, it runs with **`--tools ""`**. That is the enforcement, not a
convention it is asked to respect — a main agent with no file tools cannot
quietly do the work itself on a turn where delegating felt slow.

**Which also makes it the cheapest process in the system.** With no tool
schemas to load, no skills, no MCP and Claude Code's system prompt replaced,
its measured carrier cost is the **805-token floor**, plus whatever her own
prompt costs on top (§4.9.1) — **2,523 tokens** if the v2 main agent prompt
ends up the size of v1's `assistant.md`. The process that takes every single
turn is the cheapest thing v2 runs.

**Returning intents.** With no tools, the turn's output is text. `claude -p`
takes `--json-schema`, which validates structured output against a schema — so
the *create / ask / clarify / spawn / done* intents of §4.8 come back as
validated JSON rather than prose the runtime has to parse hopefully. **OPEN —
the intent schema itself is not yet written.**

The **task list** is not an exception. It is runtime bookkeeping, not memory,
and the *runtime* writes it from the intents the turn returns. The agent never
edits it directly, so intent (2) above is still just words coming out of a
model.

Consequence, accepted: the **ack is slower** — it can't be written until the
writing sub-agent finishes, so seconds rather than milliseconds. In exchange
the main agent's turn stays as short as it can possibly be, which is what
availability actually costs. Her wait to send the *next* note is minimal; her
wait for the *confirmation* is longer. That ordering matches the priority.

**Session reset on request.** Beyond the automatic 40% reset, she can tell the
agent *"when you're done with this, reset the session."* The reset is
**deferred until the current note is fully processed** — sub-agents spawned,
memory written, reply sent, ack written — and only then is the session dropped.
It is a runtime instruction, not a slash command, since v2 has no slash
commands. Trace: `session_reset` with `reason: requested | context_40pct`.

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

**How the agent knows what exists, given it has no tools.** *Resolved
2026-08-31 — this was an unclosed hole.* With `--tools ""` the main agent cannot
check a path, so the runtime injects a **`DESTINATIONS` block** into every turn:
the current memory tree, plus which folders carry a `CLAUDE.md`. The agent may
route only to something in that block, or to `others/`. The `CLAUDE.md` flag is
also what lets it satisfy the §4.9.1 repair — naming the right context file in
an instruction — without guessing.

The memory structure is unchanged from v1 — `projects/`, `miniprojects/`, root
files, `reference/`. No restructuring. All 142 existing destinations remain,
and that is harmless because nothing searches that space blindly.

Trace: `route_decided`, recording destination and whether it was declared or
inferred.

11. Write to memory. Trace: `memory_written` with path and action.

**Retrieval — the other half of the job.** *Ruled 2026-08-31.* "What did I say
about the collage refs", "where are my notes on seldon", "what did you file
yesterday" are all work, and the main agent cannot look anything up itself. It
creates a task and spawns a **read-only worker** (`kind: "search"`) with an
explicit search instruction — which subtrees, which terms and likely
misspellings, and *return the matching lines with their paths, not a
paraphrase*. Questions about **what happened** rather than what she wrote are
answered from the trace, not the memory tree. The answer is relayed in the main
agent's own words, with the paths, so she can go read the thing herself.

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

### 4.8 The task list — clarify first, delegate second

*Ruled 2026-08-31.* Not everything she says is a note to file. Some of it is
**work to do**, and work has a lifecycle that the main agent owns end to end.

**Only the main agent talks to her.** Sub-agents have no channel to Janhavi —
not for questions, not for progress, not for completion. Every word she reads
in Telegram was written by the main agent. Everything below exists to serve
that one rule.

The main agent keeps **two lists**:

- **`unclear`** — work that cannot be started, because something about it needs
  her answer.
- **`working`** — work that is fully specified, and either running or queued.

A task moves between them in **both** directions:

```
        she asks for something
                  │
                  ▼
            ┌───────────┐
            │  UNCLEAR  │ ◄──────────────────┐
            └─────┬─────┘                    │
                  │  main agent asks her     │
                  │  over Telegram           │
                  ▼                          │
            she answers                      │
                  │                          │
                  ▼                          │
            ┌───────────┐                    │
            │  WORKING  │                    │
            └─────┬─────┘                    │
                  │  sub-agents run          │
        ┌─────────┴─────────┐                │
        ▼                   ▼                │
   returns done      returns a question ─────┘
        │
        ▼
      DONE  ──► she is told
```

**Step by step.**

1. She asks for something. If the main agent cannot fully specify the work from
   what she said, the request lands in `unclear` **before any question is
   asked** — the same park-first rule as `others/` (§4.7), for the same reason:
   a question that never gets answered must not be able to lose the request.
   Trace: `task_created` with `state: unclear`.
2. The main agent asks her over Telegram, in its own voice, as one message.
   Trace: `task_question_asked`.
3. She answers. The main agent folds the answer into the task and moves it to
   `working`. Trace: `task_clarified`.
4. It breaks the task into subtasks and spawns a sub-agent per subtask, each
   with a self-contained instruction (§4.9). The task record holds every
   sub-agent's id **and the exact instruction it was given**.
   Trace: `subagent_spawned`.
5. A sub-agent finishes. Two outcomes matter:
   - **Done.** When every sub-agent on a task is done, the task is done and she
     is told. Trace: `task_done`.
   - **Needs her.** The sub-agent's *result* is a question. The task goes
     **back to `unclear`** and the loop re-enters at step 2.
     Trace: `task_blocked`, then `task_question_asked`.

**A sub-agent question is a terminal state, not a channel.** This is how the
loop above coexists with the mailbox staying dropped (§8). A stuck sub-agent
does not wait, does not poll, and never messages her — it **exits**, and its
return value is `needs_input` plus the question. The main agent reads that like
any other result. Nothing is bidirectional, and nothing is left running while a
question sits unanswered for a day.

**Resuming means re-spawning.** Sub-agents are stateless and have already
exited by the time she answers, so there is nothing to resume. The main agent
writes a *new* self-contained instruction that folds in her answer, and spawns
a fresh sub-agent. This falls straight out of the bare-prompt rule in §4.9 and
costs nothing extra.

**Waking the main agent — the one new piece of machinery.** Her notes can no
longer be the only thing that starts a main agent turn. A sub-agent finishing
has to start one too, or step 5 never happens until she happens to speak. So
**sub-agent terminal results enter the same serialized turn queue as incoming
notes**, in arrival order. One queue, one turn at a time, whichever the source.
Without this the flow deadlocks, so it is not optional; with it, the main agent
stays exactly as simple as §4.5 describes.

**The runtime writes the list, not the agent.** The main agent's turn returns
intents — *create this task*, *ask this*, *mark this clear*, *spawn these* —
and the runtime performs them, writing a trace event for each. `tasks.json` is
a **projection of the trace**, rebuilt as those events are written. Same
pattern as the ack (§4.11): one source of truth, no second file to drift.

**A finished task leaves the list — and no cleanup daemon is needed.**
*Ruled 2026-08-31: "if the task is done, we can remove it from the main agent's
list. why bloat it."* Because the list is a projection, this needs no sweeper,
no schedule, and no second process: folding a `task_done` event simply **drops
the task from the live list**. It never enters and then gets cleaned up.

That is worth stating plainly, because a cleanup daemon was the obvious
alternative and it is strictly worse — it would be another process to
supervise, it could race with a turn in flight, and it would exist only to
delete state we never needed to keep. **`done` is an event, not a state.** The
live list holds exactly two states, `unclear` and `working`, and nothing else
can accumulate in it.

Nothing is lost by dropping it: every task that ever existed is in the trace
permanently, with its question, her answer, and each sub-agent's verbatim
instruction. *"What did you finish last Tuesday"* is a grep, not a list scan.

**One concession to usability: a five-line done-tail.** The last ~5 completed
tasks are injected as one line each — id, one-line request, when. Without it,
*"actually, change that thing you just did"* has nothing to bind to. Five lines
is a rounding error against the 40% budget, and the full history stays on the
board (§4.11) rather than in the prompt.

A task record:

```json
{
  "task_id":   "t_0041",
  "state":     "unclear",              // unclear | working — `done` is an event, not a state
  "trace_id":  "upd_884213",
  "request":   "add the collage refs to the mirror's next todos",
  "created":   "2026-08-31T14:30:41+05:30",
  "question":  "which mirror page — the seldon one or the collage one?",
  "answers":   [ { "ts": "2026-08-31T14:33:02+05:30", "text": "the collage one" } ],
  "subagents": [
    { "id": "sa_0112",
      "instruction": "…verbatim, self-contained…",
      "status": "needs_input",
      "result": "which format for the refs list — bullets or a table?" }
  ]
}
```

**The full list is injected at the top of every main agent turn.** That is what
makes the 40% session reset (§4.5) survivable: the session is disposable
precisely because the task state was never held inside it.

**Visible two ways, like everything else that can go quiet.** Both lists render
on the board as a top-level section (§4.12), `unclear` with a count. And `unclear` is loud by construction —
every entry in it corresponds to a question she was actually asked over
Telegram. There is no path by which a task sits unclear without her having been
told.

> **`unclear` and `others/` are different things.** `others/` is a *note whose
> destination is unknown*; `unclear` is a *task whose instructions are
> ambiguous*. A note can be parked in `others/` with no task attached, and a
> task can be unclear with nothing to file. They stay separate on purpose, and
> they surface the same two ways.

### 4.9 Delegation

12. The main agent writes a clear instruction and spawns a sub-agent per
    subtask — including the memory write for the note itself. Concurrency is
    capped, with a queue beyond the cap. Trace: `subagent_spawned` with the
    full instruction.

**Sub-agents are stripped bare.** *Ruled 2026-08-29.* No protocols, no skills,
no `soul.md`, no identity, no personality — none of v1's `build_prompt`
scaffolding. A sub-agent receives the task instruction and nothing else.

The consequence is a hard constraint on the main agent: **every instruction
must be self-contained.** A bare sub-agent asked to "add this to the mirror's
next todos" has no idea what that means, what the file's format is, or where it
lives. The main agent must spell out the absolute path, the exact text, and the
operation. This is not optional — it is what pays for the sub-agents being
cheap and stateless.

It also makes the instruction written into the trace a complete, replayable
record of what was asked.

> **Correcting an earlier claim in this document.** An earlier draft said bare
> prompts make "token cost per sub-agent drop sharply." Measurement on
> 2026-08-31 says otherwise: the instruction was never the expensive part. A
> default `claude -p` spawn carries **27,398 tokens** of prefix before the
> instruction is even read, and more than half of that is built-in tool
> schemas. The bare-prompt rule is still right — but what it actually buys is
> the *ability* to strip the runner down, because a self-contained instruction
> needs no skills, no MCP, and no scaffolding. See §4.9.1.

13. Each sub-agent runs with `--output-format stream-json --verbose`. Every
    tool call and result is captured. Trace: `subagent_event` per line,
    then `subagent_done` or `subagent_failed`.

### 4.9.1 How a sub-agent is actually spawned

*Ruled 2026-08-31, from measurement rather than estimate.* `claude -p` loads a
large prefix by default. Measured in a clean directory, stripping one lever at
a time:

| Component | Tokens | Removed by |
|---|---:|---|
| Irreducible `claude -p` wrapper | **805** | **nothing — this is the floor** |
| Claude Code's own system prompt | 3,021 | `--system-prompt` |
| Built-in tool schemas (all of them) | 14,749 | `--tools` |
| Skills | 5,310 | `--disable-slash-commands` |
| MCP servers | 1,975 | `--strict-mcp-config` |
| CLAUDE.md / cwd context | remainder | clean working directory |
| **Default total** | **27,398** | |

**Tool schemas are more than half of it**, which is the opposite of where the
earlier draft looked. Per-tool cost above the 805-token floor:

| Tool | Tokens |
|---|---:|
| Edit | 348 |
| Write | 522 |
| Read | 608 |
| Bash | 1,358 |

**The spawn command:**

```sh
claude -p "<self-contained instruction>" \
  --output-format stream-json --verbose \
  --system-prompt "<the bare sub-agent prompt>" \
  --tools "Read,Write,Edit,Bash" \
  --strict-mcp-config \
  --disable-slash-commands \
  --exclude-dynamic-system-prompt-sections \
  --effort low \
  --max-budget-usd <cap> \
  < /dev/null
```

**What 3,355 is, precisely: the carrier cost — everything the spawn costs
*before* her own system prompt.** It was measured with `--system-prompt "x"`,
a one-character placeholder, because the real sub-agent prompt is not written
yet (§9). Her prompt is then added on top.

Using v1's prompts as size anchors, measured the same way:

| | carrier | + real prompt | prompt costs |
|---|---:|---:|---:|
| Sub-agent, `Read,Write,Edit,Bash` | 3,355 | **3,858** (v1 `executor.md`) | 503 |
| Main agent, `--tools ""` | 805 | **2,523** (v1 `assistant.md`) | 1,718 |

So the honest like-for-like figure is **27,398 → 3,858, an 85.9% reduction**
— the default baseline includes Claude Code's own 3,021-token system prompt,
so comparing it against a one-character placeholder would flatter the result by
about 3k. `mcp_servers: []` confirmed empty either way.

**Which gives a useful budget.** Replacing Claude Code's system prompt is a
straight swap: her prompt has to exceed **3,021 tokens (~8.5 KB)** before the
replacement costs more than it saves. v1's `executor.md` spends 503 of that —
17% of the budget. There is a great deal of room, and no reason to write the
sub-agent prompt tersely to save tokens.

For planning: her markdown prompts measure **~2.8 bytes per token**, not the
usual rule-of-thumb 4 — `executor.md` is 1,426 bytes → 503 tokens,
`assistant.md` is 4,690 bytes → 1,718 tokens.

**The tool set, and why it is exactly these four.** *Ruled 2026-08-31: "I just
need terminal tool and browser and that's it."*

- `Read`, `Write`, `Edit` — the memory writes, which are the whole job.
- `Bash` — the terminal. It is the most expensive schema of the four and it is
  the one that lets a sub-agent wander, but she keeps it deliberately.
- **The browser needs no tool.** `silicon` is a CLI at `~/.local/bin/silicon`
  (`silicon browser [name]` opens a headed browser), so `Bash` already reaches
  it. This is the reason **zero MCP servers are needed** — the one capability
  that looked like it required one turned out to be a command.

**No skills.** *Ruled 2026-08-31: "I don't need any skill."* v1's skill
scaffolding does not apply to a sub-agent that receives a complete instruction.

**No MCP.** All ~30 servers inherited from the work `claude.ai` account are
dropped. They currently cost only ~2k because every one reports "needs
authentication" and never loads its schemas — authenticate any of them and that
number climbs. `--strict-mcp-config` with no `--mcp-config` is the permanent
fix, not a cleanup.

> **The one thing stripping breaks, and how it is repaired.** `~/bismuth-memory`
> holds **5 per-folder `CLAUDE.md` files** (~10.6 KB) — her deliberate rule that
> each folder's context lives beside its data. A stripped sub-agent in a clean
> working directory does not see them.
>
> The repair is better than the auto-discovery it replaces: **the main agent
> names the `CLAUDE.md` path in the instruction**, or inlines the lines that
> matter. The sub-agent has `Read`. This turns an implicit mechanism into an
> explicit step that lands in the trace — and it is exactly what the
> self-contained-instruction rule already demands. Stripping is safe *because*
> that rule exists.

**Two operational details that are easy to miss and cost real time:**

- `< /dev/null` is not decoration. Without it every spawn stalls **3 seconds**
  waiting on stdin — pure added latency on her ack, on every sub-agent.
- `--bare` looks ideal and **cannot be used.** It skips hooks, LSP, plugin sync
  and CLAUDE.md discovery, but it refuses OAuth and the keychain outright and
  demands `ANTHROPIC_API_KEY`. On her subscription login it returns *"Not
  logged in · Please run /login"*. Using it would mean paying API rates
  separately from the subscription.

**`--max-budget-usd` partly closes a gap §7 records as unguarded.** It is not a
kill switch for the main agent, but it bounds the blast radius of a runaway
sub-agent. That failure is not hypothetical: on a one-line file append, a
default-configured spawn reached **118,011 tokens and $0.37** because it had
the full tool set and chose to shell out through `Bash` three times, with every
command's output re-entering context. The same task on the stripped config used
`Read` then `Edit`, and cost **8,092 tokens and $0.024** — 15× cheaper, and
correct both times.

That is the deeper reason to cut the tool list: it does not merely shrink the
prefix, it removes the expensive paths the agent can wander down.

**Sub-agents are `claude -p`, and v2 does not plan around anything else.**
*Ruled 2026-08-31.* No abstraction over the runner, and the trace records
`claude -p`'s stream-json directly rather than a normalised schema invented for
a second model that does not exist (§5).

**Sub-agents are trusted.** Nothing independently verifies that the work
claimed was actually done. This is a known, accepted gap — issue #18.

**Sub-agents never message her.** *Ruled 2026-08-31.* There is no mailbox, no
progress channel, no back-and-forth. A sub-agent has exactly three ways to end:

| Terminal status | Meaning | What the main agent does |
|---|---|---|
| `done` | the work is finished | closes the subtask; tells her when the task is complete |
| `needs_input` | it cannot proceed without her answer | moves the task back to `unclear` and asks her (§4.8) |
| `failed` | it broke | tells her, with the error |

`needs_input` is what makes §4.8's loop work without reintroducing the mailbox.
The sub-agent **exits** carrying its question as a return value; it does not
sit waiting for a reply. The relay to her is the main agent's job, on a later
turn, in the main agent's voice.

### 4.10 Reply

14. **The main agent** replies over **Telegram**: text, voice notes via
    `sendVoice`, images, video, documents, links.

**Every message she receives is the main agent's.** Nothing else in the runtime
holds the Telegram send credential in a way it is allowed to use for content —
not sub-agents, not watchers, not the board. Failures and `others/` questions
are relayed *by the main agent*, phrased by the main agent. One voice, so that
the chat never reads like several programs talking over each other.

Prompt rule from her architecture note holds: do not emit 200–300 lines. Write
big things to a file, upload it, send the link, and summarise. Trace:
`reply_sent`, **text only — no audio files are kept.**

Voice replies are generated by `tools/tts.py` (macOS `say`) and delivered as
real playable Telegram voice notes. `say` sounds like `say`; swapping in a
hosted TTS later means editing `tools/tts.py`, which is a small file.
**OPEN — Q8**, low priority; she'll decide on first listen.

The external-speaker path from her architecture voice note is **deferred, not
deleted.**

### 4.11 Acknowledgement

With no app on the phone there is nowhere to show a quiet per-note receipt, so
the ack changes shape. It is written as a trace event and **rendered on the
board** — for the last N notes: transcript snippet, where it landed, and
whether it's on the board.

**It does not get main-space billing.** *Ruled 2026-08-31: "we can show ack on
board but keep it somewhere not occupying the main space."* Acks live in a
secondary strip at the foot of the board, along with recently-completed tasks
(§4.8). The reasoning is the same as the quiet/loud split below: an ack is
reassurance she goes looking for, not information she needs pushed at her. The
main space belongs to what is live — projects, tasks, reminders.

```json
// trace event: ack
{
  "ts":            "2026-08-31T14:30:41+05:30",
  "type":          "ack",
  "trace_id":      "upd_884213",
  "status":        "saved",           // saved | others | failed
  "transcript":    "…",
  "destinations":  [
    { "path": "projects/the_mirror/nexttodo.md", "action": "append" }
  ],
  "on_board":      true
}
```

**The quiet/loud split survives the change, which is the important part.** Acks
are silent — she looks at the board when she wants reassurance, and is not
buzzed once per dictated note. If every note pushed "saved to …" to Telegram
she would mute the channel inside a week and then miss the messages that
matter.

Telegram is used only when it should be loud: `others/` questions, failures,
sub-agent results, and answers she asked for.

Single source of truth: the ack lives in the trace, and the board reads it.
There is no separate receipts file to drift.

### 4.12 Board

17. `tools/board.py` regenerates `board.html` from the memory tree and the
    trace.

R1 froze the board's design and v2 does not redesign it. What v2 adds is
**two new sections and one strip** — additions, not changes to anything that
already renders.

**Main space — a `Tasks` section, peer to the existing ones.** *Ruled
2026-08-31: "they can be shown as a new section like projects miniprojects and
reminders."* It renders the two live lists from §4.8:

```
┌─ Tasks ──────────────────────────────────────────────┐
│                                                       │
│  NEEDS YOU  (2)                                       │
│   • collage refs → which mirror page?      asked 14:31│
│   • trip notes   → bullets or a table?     asked 09:02│
│                                                       │
│  WORKING  (3)                                         │
│   • seldon essay outline          2 sub-agents running│
│   • resume bullet rewrite                    1 running│
│   • reminders tidy-up                         1 queued│
└───────────────────────────────────────────────────────┘
```

`NEEDS YOU` carries a count and sits above `WORKING`, because it is the only
part of the board that is waiting on *her*. `others/` keeps its own panel with
its own count, for the reason in §4.8 — an unrouted note and an ambiguous task
are different problems.

**Secondary strip — acks and recently-done.** At the foot of the board, out of
the main space: the last N note acks (§4.11) and the last N completed tasks.
Both are "did that land?" reassurance, and neither is live work.

Everything on the board is read from the memory tree and the trace. The board
holds no state of its own, so it can be regenerated from scratch at any time
and can never disagree with the record.

---

## 5. Trace (R4)

`~/bismuth-memory/trace/log-YYYY-MM.jsonl` — append-only JSONL, one object per
event, date-partitioned so "what did you do on the 14th" is a file lookup.

**No rotation. Ever. Nothing is unlinked or overwritten.** `rotate_log()` and
`LOG_KEEP` do not carry over from v1.

**Every event carries `ts`, `seq`, and `trace_id`.** *Strengthened
2026-08-31 — "I hope all events in trace are saved with time so I can sort on
it and see what happened in what order."*

| Field | What | Why |
|---|---|---|
| `ts` | ISO 8601, local time **with offset** — `2026-08-31T14:30:41+05:30` | human-readable, and answers "what happened on the 14th" |
| `seq` | a global, gapless, monotonically increasing integer | **the authoritative order** |
| `trace_id` | Telegram's `update_id` | joins every event for one note |

`seq` exists because `ts` alone is not a safe sort key, for two reasons that
will both actually happen: a main agent turn can spawn four sub-agents inside
the same millisecond, and if she travels or DST shifts, timestamps with
different offsets no longer sort lexicographically. `seq` has neither problem.
It is assigned under the same lock that appends the line, so it is gapless —
**a gap in `seq` means an event was lost**, which makes the completeness of the
trace checkable rather than assumed.

So: sort by `seq` for exact order, read `ts` to know when, filter `trace_id` to
follow one note end to end. The whole record, in order, is:

```sh
cat ~/bismuth-memory/trace/log-*.jsonl | jq -s 'sort_by(.seq)'
```

| Event | Fields |
|---|---|
| `note_received` | update_id, telegram_date, bytes, kind |
| `audio_archived` | trace_id, archive_path, sha256, bytes |
| `audio_pushed` | commit, files, or the error if the push failed |
| `stt_done` | transcript, model, duration_sec |
| `route_decided` | destination, mode (declared \| inferred) |
| `memory_written` | path, action, bytes |
| `parked_in_others` | path, reason |
| `task_created` | task_id, state (unclear \| working), request |
| `task_question_asked` | task_id, question |
| `task_clarified` | task_id, answer, new_state |
| `task_blocked` | task_id, subagent_id, question |
| `task_done` | task_id, subagent_ids |
| `subagent_spawned` | task_id, subagent_id, instruction (verbatim) |
| `subagent_event` | subagent_id, stream-json line |
| `subagent_done` / `subagent_failed` | subagent_id, status, summary or error |
| `agent_event` | session_id, stream-json line from the main agent |
| `turn_usage` | session_id, input/output/cache tokens, running total, pct of window |
| `session_reset` | reason (requested \| context_40pct), old_session, window_size |
| `reply_sent` | channel, kind, text |
| `ack` | status, transcript, destinations, on_board |
| `retry_queued` | update_id, reason, attempt |

The five `task_*` events are the whole of §4.8. `tasks.json` is rebuilt from
them and holds no fact they do not already contain — so "what did you ask me
about on the 14th, and what did I say" is a grep, permanently.

### What `claude -p` gives us, and what it does not

*Asked 2026-08-31: "claude -p can give us the complete trace of itself right?
it is costless right? I want that asked of it, main agent and sub agents both."*

**Both are captured.** `--output-format stream-json --verbose` is used for the
main agent (`agent_event`) as well as sub-agents (`subagent_event`). Every line
is appended to our trace as-is.

**Token cost: yes, genuinely free.** The stream is the model's own output
re-rendered as JSON. There are no extra API calls and no extra tokens —
requesting it costs nothing beyond the work being done anyway.

**Disk cost: not free, and this is the one to watch.** A single tool result can
be an entire file read or a grep across the memory tree. This is by far the
largest contributor to trace size, and with no rotation (below) there is
nothing else holding it back — hence the per-event size cap.

**What it contains:** every assistant message, every tool call with its full
input, every tool result, and a final `result` message carrying token usage and
cost. That final message is also what feeds the 40% session-reset rule (§4.5) —
it turns a running *estimate* into an exact number.

**What it does not contain — worth being straight about.** It is a complete
record of **what the agent did**, not of **why it decided**. Reasoning is not
in the stream unless extended thinking is enabled, and even then thinking
blocks are not a decision rationale. So R4 is satisfied in the sense she asked
for — every action, every input, every output, in order, permanently — and the
*motive* behind a routing choice is inferable from `route_decided` and the
instruction text, not stated by the model.

The main agent's stream is thin by design: it runs with no tools (§4.5), so its
events are assistant text, the intents it returned, and usage. The sub-agents
are where the volume is.

**`subagent_event` stores `claude -p`'s stream-json line as-is.** *Ruled
2026-08-31.* An earlier draft proposed normalising it into a model-neutral
`{tool, input, output, ok}` shape. That is dropped along with the rest of the
pluggability layer: the runner is `claude -p`, so a translation layer would
exist only to serve a second runner that is not planned. If one is ever wanted,
the raw lines are all still on disk and can be re-read into any shape then.

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

*Asked 2026-08-31: "is there a dictionary somewhere in code that has all that?
or is it an idea of state whose components can be retrieved from places?"*

**Both, and the split is deliberate.** There is one real dictionary, and it is
deliberately small. Everything else is either derived from the trace or dies
with the process. The organising question is **what breaks if you delete it:**

### Tier 1 — authoritative. One file, one dict.

`~/.bismuth/state.json`. Losing any of this loses work, so it is written
atomically and always *before* the thing it records.

| Key | What | Delete it and… |
|---|---|---|
| `offset` | Telegram's `getUpdates` offset | messages replay (safe — dedup catches them) |
| `processed_ids` | dedup ledger on `update_id` | replayed messages get processed twice |
| `turn_queue` | serialized main agent input: notes **and** sub-agent results, in arrival order | **work is lost** — a finished sub-agent's result never reaches the agent, and its task hangs in `working` forever |
| `session` | main agent session id, started_at, window_size, running token total | the session is orphaned; a fresh one starts |

`turn_queue` is the one that carries the strictest discipline, and for the same
reason as the ingest offset: a sub-agent result is written durably **before**
the sub-agent's process is reaped. The write is the commit point.

### Tier 2 — derived. Cache only, rebuilt from the trace.

Delete any of it and the runtime reconstructs it at boot by folding the trace.
It is written to disk only so a restart is fast, never because it is the truth.

| File | Folded from |
|---|---|
| `tasks.json` | the `task_*` events (§4.8) |
| `subagents.json` | `subagent_spawned` / `subagent_done` / `subagent_failed` |

This is what makes §4.8's "no cleanup daemon" work, and it is the whole reason
the trace is the single source of truth rather than one record among several.

### Tier 3 — ephemeral. In memory, dies with the process.

Running `Popen` handles, open sockets, the concurrency semaphore, the queue of
sub-agents waiting on the cap. None of it is persisted, and none of it needs to
be, because of what happens next.

### Boot reconciliation — where the tiering pays off

On every start, before the main loop:

1. Load tier 1.
2. Rebuild tier 2 by folding the trace forward.
3. **Reconcile.** Any sub-agent with a `subagent_spawned` event and no terminal
   event was killed by the crash — its process is gone with tier 3. It is
   marked `failed`, a `subagent_failed` event is written with
   `reason: "runtime restart"`, and its task returns to `unclear` so the main
   agent tells her rather than leaving it stuck in `working`.

That step is only expressible because the tiers are separated. If everything
lived in one dictionary there would be no way to tell "this sub-agent is
running" from "this sub-agent *was* running before we died" — which is exactly
how v1 accumulated 113 dead-lettered entries nobody was ever told about.

State is written atomically. Concurrent writers to shared memory files use file
locks, as v1 did.

---

## 7. Failure modes

The R3 section. For each, what happens, and where she can see it.

| Failure | Behaviour | Visible where |
|---|---|---|
| No signal on the phone | Telegram's own client queues and retries the send | Telegram's per-message send indicator |
| Telegram unreachable from laptop | Offset not advanced; messages served again when it returns | trace |
| Laptop asleep / off | Message waits on Telegram's servers indefinitely | Telegram chat |
| Runtime crashes mid-note | Offset not yet advanced → message redelivered on restart; dedup ledger makes reprocessing a no-op | trace |
| STT fails | Offset not advanced past it; ack `status: failed`; she is told | Telegram + board |
| Processing fails repeatedly | Visible retry queue, **never a silent dead-letter** | Telegram + board count |
| Destination doesn't exist | Parked in `others/`, then asked | board + Telegram |
| She never answers the question | Note stays in `others/` | board count |
| Sub-agent fails | Main agent tells her, with the error | Telegram + trace |
| Sub-agent needs her input | Task returns to `unclear`; main agent asks her | Telegram + board count |
| She never answers a task question | Task stays in `unclear` — never silently dropped, never auto-guessed | board count |
| Sub-agent result arrives while a turn is running | Waits its place in `turn_queue`; one turn at a time | trace |
| `tasks.json` lost or corrupt | Rebuilt from the `task_*` trace events | trace |
| Sub-agent silently does nothing | **Not detected** — known accepted gap | issue #18 |
| Audio archive push fails | Audio sits in the local working tree; retried next tick. **The note is unaffected** — archiving is off the critical path (§4.1) | trace |
| Runtime dies with sub-agents running | Boot reconciliation marks them failed and returns their tasks to `unclear`, so she is told (§6) | Telegram + board |
| `tasks.json` / `subagents.json` lost | Rebuilt from the trace at boot | — |
| `turn_queue` lost | **Work is lost** — the one piece of state with no rebuild path; written before a sub-agent is reaped (§6) | trace gap in `seq` |
| Rate limit hit | Notes wait in the queue | trace |
| Context reaches 40% | New session starts automatically | trace |
| Runaway sub-agent | Bounded by `--max-budget-usd` per spawn (§4.9.1) | trace |
| Runaway work (main agent) | **No kill switch** — process must be killed by hand | — |

Two of these are unguarded by explicit choice: sub-agent honesty, and the
absence of a stop command. Both are recorded rather than argued.

---

## 8. What v1 has that v2 drops

| Dropped | What it did | Cost of dropping |
|---|---|---|
| **coffeechat** | per-project thinking-partner agent | no brainstorming mode; returns later as a sub-agent if wanted |
| **watchers** | `daily_reminder`, `fs_dropbox`, `twitter_daily` + supervisor | **nothing reaches Bismuth that she didn't say.** No 09:00 reminder surface, no dropbox pickup. `reminders.md` becomes passive |
| **synthetic inbox** | how watchers poked the agent | n/a once watchers go |
| **mailbox** | sub-agent → her questions, and DONE/FAILED relay | none — replaced by sub-agent terminal statuses relayed by the main agent (§4.8, §4.9) |
| **`/status`** | no-LLM introspection | no way to see what's running without asking the agent |
| **`/halt`** | no-LLM emergency stop | no kill switch |
| **iOS Shortcut + GitHub inbox** | designed 2026-08-28, dropped 2026-08-31 | none — Telegram was already doing the same job for free, with less to build and nothing to install on the phone |
| **pluggable seams** | adapter interfaces for transport / STT / TTS / runner | none — *ruled 2026-08-31*: the stack is fixed, and swapping any one piece later is a day of work either way (§1) |
| **log rotation** | 10 MB, keep 3 | none — this is the point |
| **batching** | multiple messages per turn | none — serialization is the choice |

This is a much smaller system than v1. That is the intent: R3 is "no clutter,
and a Bismuth I can trust", and every component removed is one that can't fail.

---

## 9. Open items

Blocking the low-level design:

- *(nothing — the two blocking items below closed on 2026-08-31.)*

- **Q13 — refactor `harness.py`, or a new lean process?** With watchers,
  mailbox, synthetic inbox, slash commands and coffeechat all gone, several
  hundred lines of v1's harness no longer apply. What v2 still wants is narrow:
  the disk spool, `claude -p` invocation with resumable sessions, stream-json
  parsing, sub-process lifecycle with cap and queue, file locks, state
  persistence. **Recommendation: a new lean process that ports those pieces.**

Closed since the last draft:

- ~~**The two prompts are not written.**~~ **Closed 2026-08-31.** Written, and
  measured: main agent 4,779 tokens total prefix, sub-agent 5,063 (§10).
- ~~**The main agent's intent schema is not written.**~~ **Closed 2026-08-31.**
  `prompts/v2/intent_schema.json` — eight intent types, flat objects rather than
  a discriminated union, per-type requirements enforced by the prompt.
- ~~**How does a tool-less main agent know which destinations exist?**~~
  **Closed 2026-08-31.** A `DESTINATIONS` block is injected every turn (§4.6).
- ~~**Completion notification.**~~ **Closed 2026-08-31.** The main agent owns
  the relay. Sub-agents end in `done` / `needs_input` / `failed`, and the main
  agent tells her — completion, question, or failure, all in one voice (§4.8,
  §4.9).
- ~~**Open-weight models for sub-agents.**~~ **Closed 2026-08-31.** `claude -p`
  stays for both the main agent and sub-agents. Not revisited in v2.
- ~~**Pluggable seams.**~~ **Closed 2026-08-31.** Dropped in favour of the
  fixed stack in §1.
- ~~**Incoming audio retention.**~~ **Closed 2026-08-31.** Kept forever, in a
  separate private repo, archived off the critical path (§4.1).

Not blocking:

- **Q8 — TTS voice.** Decides itself on first listen.
- Pickup cadence — long-poll vs the 5-minute interval, which was a GitHub
  artefact (§4.2).
- Trace size once main-agent streams are captured too. The per-event cap
  covers the runaway case; steady-state volume is an empirical question that
  answers itself in the first week.

---

## 10. The two prompts

**Both prompts now exist**, written 2026-08-31 against the checklist below:

| File | What it is |
|---|---|
| `prompts/v2/main_agent.md` | the main agent's `--system-prompt` |
| `prompts/v2/subagent.md` | the sub-agent's `--system-prompt` |
| `prompts/v2/intent_schema.json` | `--json-schema` for the main agent's turn output |
| `prompts/v2/subagent_result_schema.json` | the shape of a sub-agent's final message |
| `prompts/v2/OUTLINE.md` | the responsibility outline they were drafted from |

Measured the same way as §4.9.1 — carrier with a placeholder prompt, then the
real file:

| | carrier | with real prompt | prompt costs |
|---|---:|---:|---:|
| Main agent, `--tools ""` | 805 | **4,779** | 3,974 |
| Sub-agent, `Read,Write,Edit,Bash` | 3,355 | **5,063** | 1,708 |

Both carriers reproduced §4.9.1's figures exactly. Against the 27,398-token
default spawn, the sub-agent is an **81.5% reduction**. The sub-agent spends
57% of the 3,021-token swap budget; the main agent exceeds it by 953, which is
recorded rather than trimmed — the budget measures a *swap*, and Claude Code's
own prompt does none of this job.

Three things the checklist below did not anticipate, added while writing:
**retrieval** (§4.6), the **`DESTINATIONS` block** (§4.6), and the sub-agent's
**read-back self-check**. One thing it did anticipate is now cut: the main
agent carries no companion/brainstorming behaviour, per the scope ruling in §1.

**The checklist, written 2026-08-31, before either prompt existed.** After stripping (§4.9.1),
these two strings are the *only* behavioural content in the entire system —
no skills, no protocols, no `soul.md`, no MCP. Everything either agent knows
about how to act comes from here. This section is the checklist to write them
against; every line traces to a ruling elsewhere in this document.

**Budget first, so neither is written tersely for the wrong reason.** Replacing
Claude Code's system prompt is a swap with a **3,021-token allowance** before it
costs anything (§4.9.1). v1's `executor.md` spends 503 — 17%. There is ample
room. Write what the agent actually needs; do not compress to save tokens.
Planning ratio for her markdown: **~2.8 bytes/token**.

### 10.1 The sub-agent prompt

The smaller of the two, and the one to write first — it is fully specified by
rulings already made, and it is what build-order step 5 needs.

Must establish:

- **Do exactly the instruction, nothing more.** No tidying, no adjacent
  improvements, no refactoring the file it was asked to append one line to.
- **The instruction is complete.** It will name absolute paths, exact text, and
  the operation (§4.9). It does not need to infer intent, and should not try.
- **It has four tools** — `Read`, `Write`, `Edit`, `Bash` — and `Bash` reaches
  the `silicon` CLI for browser work (§4.9.1). Prefer `Read`+`Edit` over
  shelling out; the measured cost of choosing `Bash` for a file append was 118k
  tokens against 8k (§4.9.1).
- **It ends in exactly one of three states** — `done`, `needs_input`, `failed`
  (§4.9). The terminal status is the entire protocol.
- **`needs_input` means exit, carrying the question as the return value.** It
  does not wait, poll, retry indefinitely, or attempt to reach Janhavi.
- **It never messages her.** There is no channel. Anything it wants her to know
  goes in its return value, and the main agent decides what to relay (§1).
- **It has no identity and no personality.** *Ruled 2026-08-29.* It is not
  Bismuth; it is a worker Bismuth spawned.
- **Terse output.** Its return value is read by a program and written to the
  trace, not by a human.

Must **not** contain: anything about Telegram, the board, the task list,
`others/`, routing, or the memory tree's structure. A sub-agent that knows
about those has been given a job it should not have.

> **The known gap this prompt cannot close.** Nothing verifies that a sub-agent
> did what it claims (§4.9, issue #18). Prompt wording does not fix that, and
> should not pretend to.

### 10.2 The main agent prompt

Larger, and the harder of the two — it carries every judgment in the system.

Must establish:

- **It does no work at all.** *Ruled 2026-08-29, restated 2026-08-31.* Not "no
  memory writes" — nothing. It runs `--tools ""` so this is enforced, not
  requested (§4.5), but the prompt must still say it, because its output is
  *instructions for work* and the distinction has to be legible to it.
- **Its three outputs**: sub-agent instructions, task-list intents, replies to
  her (§4.5).
- **Every instruction it writes must be self-contained** — absolute path, exact
  text, exact operation — because the sub-agent receiving it knows nothing
  (§4.9). This is the single highest-leverage paragraph in either prompt.
- **It names the relevant `CLAUDE.md` path in the instruction**, or inlines the
  lines that matter, since a stripped sub-agent does not auto-discover the 5
  per-folder files in `~/bismuth-memory` (§4.9.1).
- **Routing.** Declared destinations are normal and verifiable; inference is
  allowed when she does not declare; **the destination must already exist**; if
  it does not, the note goes to `others/` (§4.6).
- **Park first, then ask.** Both for `others/` and for unclear tasks — the note
  or request is durable *before* any question is asked (§4.7, §4.8).
- **The task lifecycle** — `unclear` → ask → clarify → `working` → sub-agents →
  `done`, or back to `unclear` when a sub-agent returns `needs_input` (§4.8).
- **One voice.** Only it talks to her. Failures, questions, completions — all
  relayed in its own words, never pasted raw from a sub-agent (§4.10).
- **Quiet by default.** Acks are silent and live on the board. Telegram is used
  only when it should be loud: `others/` questions, task questions, failures,
  completions, answers she asked for (§4.11).
- **Reply length.** Do not emit 200–300 lines. Write big things to a file,
  upload it, send the link, summarise (§4.10).
- **Stay available.** A second note may arrive seconds later; her wait is
  exactly this agent's turn length, so keep the turn short by delegating
  rather than deliberating (§4.5).
- **Session reset on request** is deferred until the current note is fully
  processed (§4.5).

~~**OPEN — the intent schema.**~~ **Closed 2026-08-31.**
`prompts/v2/intent_schema.json`: `{"intents": [ … ]}` performed by the runtime
in listed order, an empty list meaning silence. Eight types — `route`,
`task_create`, `task_ask`, `task_clarify`, `spawn`, `task_done`, `reply`,
`session_reset`. Flat objects rather than a `oneOf` discriminated union, because
structured-output validators handle unions inconsistently and a schema the
runtime rejects is worse than one that under-constrains; the prompt carries the
per-type strictness.

---

## 11. Build order

Cutover is **hard — v1 stops**, no parallel run. Since v1 and v2 now share the
same Telegram bot, they cannot both poll `getUpdates` at once — two consumers
of one offset will steal each other's messages. So v2 must be built against a
**second bot token** and only pointed at the real one at cutover.

1. Ingest + trace: `getUpdates` long-poll, disk spool, offset-after-durable,
   dedup ledger, `ts`/`seq`/`trace_id` on every event, **visible retry queue
   with no silent dead-lettering.**
   *Provable on its own — send voice notes, watch them land in the spool.*
2. Audio archive: move-to-working-tree on ingest, background push loop,
   `audio_archived` / `audio_pushed`. *Provable on its own — send a note with
   the network off and watch the note process anyway.*
3. STT wiring into the existing `tools/transcribe.py` subprocess.
4. Main agent: one session, **no tools**, serialized turns, routing decision,
   `others/`, deferred session reset, ack event, `agent_event` + `turn_usage`
   capture driving the 40% reset off real numbers.
5. Sub-agent spawning with bare prompts and self-contained instructions,
   including the memory write. Terminal statuses `done` / `needs_input` /
   `failed`. Raw stream-json trace capture.
6. **The task list and the turn queue (§4.8).** `task_*` trace events,
   `tasks.json` as their projection, sub-agent results feeding the same
   serialized turn queue as notes, and the `unclear → working → unclear` loop.
   *Provable on its own — give it a deliberately ambiguous instruction and
   watch it park, ask, clarify, delegate, and come back when a sub-agent
   returns `needs_input`.*
7. State tiering and boot reconciliation (§6): `state.json`, trace-folded
   projections, and orphaned-sub-agent recovery on restart.
   *Provable on its own — `kill -9` mid-task and watch it come back and tell
   her what died.*
8. Telegram outbound: replies, `others/` questions, task questions, failures,
   completion notices — all sent by the main agent, none by anything else.
9. Board wiring: the `Tasks` section, the `others/` panel, and the secondary
   ack + recently-done strip.
10. Run, verify against the smoke corpus, **then** stop v1.

Steps 1 and 2 are the trust foundation, and they are the whole of the hard
part: once a voice note reliably gets from her mouth into the spool and the
archive without any path that can drop it silently, everything after it is
ordinary work.
