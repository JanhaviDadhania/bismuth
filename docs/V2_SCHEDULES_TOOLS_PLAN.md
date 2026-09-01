# Bismuth v2 — Schedules & Tools Plan

Status: **Part A built 2026-09-01. Part B (the tool catalog) not started —
it waits for robot-io.** Owner: Janhavi. Bismuth implements; Janhavi confirms
each decision.

Companion to `V2_REQUIREMENTS.md` (which holds the decision log) and
`V2_ARCHITECTURE.md` (which describes the shipped runtime). Nothing here is
built on an unlogged decision — the decisions this plan depends on are listed
at the bottom, ready to be moved into the requirements log once confirmed.

---

## What this adds

Two capabilities v2 does not have:

1. **Schedules** — recurring work on a clock. "Every morning at 08:30, scroll
   twitter and write the digest."
2. **Tools** — a catalog of what a worker can reach, so the agents know a
   capability exists at all.

Both are created by talking to bismuth on Telegram. Neither requires a code
change after the initial build.

## The shape: data in reserved folders

The governing rule, and the reason this plan is small: **a schedule and a tool
are data, not code.** One generic reader is written once; after that, adding
the twentieth schedule is identical to adding the first — a file appears in a
folder. Nothing in `v2/` is ever edited again, and nothing self-modifies.

This is a direct correction of v1, where watchers were `.py` files. Adding one
meant writing Python, which is why only two ever existed.

```
~/bismuth-memory/_schedules/*.md     WHEN       clock  -> one turn
~/bismuth-memory/_tools/*.md         WHAT WITH  a card a worker reads
```

Both folders are **reserved**: invisible to `DESTINATIONS`, so an ordinary note
can never be routed into them. The mechanism already exists — `destinations.py`
line 35 skips dot-dirs generically:

```python
if any(p in SKIP_DIRS or p.startswith(".") for p in rel_parts):
```

Add `or p.startswith("_")`. Every future machine-owned folder is then reserved
automatically, and the explicit `_archive` / `_dropbox_received` entries in
`SKIP_DIRS` become redundant.

This is not cosmetic. If `_schedules/` appeared in `DESTINATIONS`, the main
agent could route a grocery list into it; `tick()` would then try to parse that
note as a schedule, and — since `_background` has no `try/except` — take audio
push, git sync and the board down with it.

---

## Part A — the scheduler

| # | File | Change |
|---|------|--------|
| A1 | `v2/schedules.py` | **new**, ~140 lines: `parse`, `is_due`, `tick`, `check_overdue` |
| A2 | `v2/config.py` | `SCHEDULES_DIR`, `SCHEDULE_TICK_INTERVAL`, both into `DIRS_TO_CREATE` |
| A3 | `v2/runtime.py` | 4th check in `_background`; **wrap all four in `try/except`** |
| A4 | `v2/state.py` | `schedules: {name: last_fired_date}` in `default_state()` |
| A5 | `prompts/v2/intent_schema.json` | `schedule_create`, `schedule_update` |
| A6 | `v2/intents.py` | two `_do_*` methods, two `VALID_TYPES` entries |
| A7 | `prompts/v2/main_agent.md` | ~10 lines: table row + "something recurring" |
| A8 | `v2/board_sections.py` | schedule panel with last-run per schedule |
| A9 | `v2/__main__.py` | `python3 -m v2 fire <name>` — dry-run one schedule |

### The schedule file

```yaml
---
every: daily              # daily | weekly | n_days
at: "08:30"
days: [sun]               # weekly only
enabled: true
budget_usd: 4.00
produces: projects/nostayidiot/twitterdaily/{date}.txt
min_bytes: 500
summary: morning tech/AI digest from x.com
---
Scroll x.com via silicon-browser, read the home timeline plus tech/AI
trending, and write the digest to
{MEMORY}/projects/nostayidiot/twitterdaily/{date}.txt.
That folder's CLAUDE.md is the contract — format, tags, honesty rule,
fallbacks. Read it first and follow it exactly.
```

### Firing semantics

- `_background` calls `schedules.tick()` about once a minute. The loop already
  sleeps 5s; a `> 60` gate makes the real granularity ~1 minute.
- **Date-guard, not interval:** due when `last_fired != today` *and*
  `now.time() >= at`. Laptop shut at 08:30 and opened at 14:00 fires at 14:00.
  Late beats never for a digest.
- Naive local `datetime.now()`, deliberately: "08:30" means wall clock.
- **`enqueue_turn` and `mark_fired` happen in one `state.mutate()` block.**
  Sequenced separately there is a crash window either way — mark-then-enqueue
  loses a run silently, enqueue-then-mark duplicates it. Both live in
  `state.json`, so one locked read-modify-write closes the window entirely.
  This is why `last_fired` is runtime state and not frontmatter the runtime
  rewrites every morning.
- `self.wake.set()` after the enqueue, so the main loop picks it up immediately
  instead of waiting out its 2s timeout.
- Schedules **do not preempt.** One queue, one turn at a time. If Janhavi is
  mid-conversation at 08:30, the schedule waits its turn. "08:30" means "the
  next free slot after 08:30."

### What the firing turn carries

The SYSTEM block carries a **pointer, not the body**:

```
SYSTEM — schedule fired
  name: twitter-daily
  file: ~/bismuth-memory/_schedules/twitter-daily.md
  summary: morning tech/AI digest from x.com
```

The main agent spawns a worker with a thin instruction — *read this file and do
what it says* — plus `claude_md` for the target folder. Rationale: inlining the
body means the main agent paraphrases it into a worker instruction, and that
retyping hop is exactly where accumulated contract detail (the hashtag scheme,
the honesty rule, the 2026-07-16 hang note) quietly disappears. Passing a path
gives the worker the authoritative text with zero paraphrase. It is also the
idiom already established by the `claude_md` field.

The one-line `summary` stays, because the main agent still has decisions to
make: spawn or merely reply, what budget, which task to attach it to, or skip
entirely if Janhavi paused it last night.

### Verification — `produces:`

A worker returning `done` does not mean the artifact is good. On 2026-07-16 the
v1 digest burned 38 turns and ~$1.53 stuck on a hung snapshot and produced
nothing, silently.

So `tick()` also runs `check_overdue()`: for any schedule with `produces:`, if
it fired more than 2h ago and the expanded path is missing or smaller than
`min_bytes`, enqueue a SYSTEM turn saying so.

Checking here rather than when reaping the worker is deliberate. Per-worker
checking needs the schedule name threaded through `SpawnRequest` and
`route_ctx`, and it still misses the worst failure — the main agent deciding
not to spawn anything at all, which nothing would ever notice. The next-tick
check catches every path: worker failed, worker lied, agent skipped, worker
never spawned.

`{date}` expands to the fire date; `check_overdue` expands with the date it is
checking.

### Board

Schedule state is read from the **trace** (`schedule_fired` events), never from
`state.json` — `board_sections.py` requires that the board hold no state of its
own so it can never disagree with the record.

---

## Part B — the tool catalog

| # | File | Change |
|---|------|--------|
| B1 | `v2/tools_catalog.py` | **new**, ~90 lines — near copy of `destinations.py`: `scan`, `render`, `fingerprint` |
| B2 | `v2/config.py` | `TOOLS_DIR`, into `DIRS_TO_CREATE` |
| B3 | `v2/mainagent.py` | `TOOLS` block in `build_turn_input`, gated like `DESTINATIONS` |
| B4 | `v2/runtime.py` | fold tools into the existing fingerprint at `process_turn` |
| B5 | `prompts/v2/main_agent.md` | ~6 lines: workers' Bash reaches these; name the tool and its card in the instruction |

### Why the main agent needs this at all

It is tempting to say the main agent does not need to know about tools, since
the worker does the work. But `destinations.py` opens with the reason it
cannot work that way:

> *The main agent runs with no tools, so it cannot check whether a path exists,
> yet the one hard routing guard is that the destination must already exist.*

The same sentence holds with "tool" for "path". Today `main_agent.md` has zero
mentions of silicon-browser, browser or web — so "scroll twitter for me" gets
answered *"I can't do that."* The agent needs the index to decide; it does not
need the manual.

```
TOOLS — a worker's Bash reaches these. Name the tool and its card in the instruction.
  silicon-browser   web pages, scrolling, screenshots, PDFs   card: _tools/silicon-browser.md
  robot-io          the arduino robot — face, hand, cam, mic  card: _tools/robot-io.md
```

~15 tokens per tool. Twenty tools is 300 tokens. It rides the existing
"first turn of a session, and again only when the fingerprint changes"
mechanism; folding tools into the single existing fingerprint is simpler than a
parallel flag, and the cost — resending DESTINATIONS' 3.2k on the rare
tool addition — is negligible.

### Card format

Only the frontmatter is parsed (`name`, `binary`, `summary`); the body is prose
for a worker to read. Malformed frontmatter means the tool simply does not
appear in the index — logged, never fatal. There is no parser to crash.

### Who writes cards

**A worker, not the runtime** — deliberately unlike schedules. A card needs
investigation: run `--help`, read the README, try a command, write down what
actually happened. A schedule is four structured fields that must be written
reliably. Long-form document that benefits from exploration → worker.
Short structured data that must not fail → runtime.

### Installing is not describing

| action | risk | who |
|--------|------|-----|
| write the card | a file write | worker, freely |
| `pip install git+https://…` | mutates the machine | **needs Janhavi's yes** |

Workers are `effort: low`, single-shot, $2-capped — right for filing, wrong for
unreviewed installs. The worker proposes the install command in its card and
ends `needs_input`; the main agent asks on Telegram; on confirmation a second
worker runs the install. All existing machinery.

The tool *packages* live outside the repo via pip, per the two-repo rule.
`_tools/` holds only the cards.

---

## Example cards

### `_tools/silicon-browser.md` — verified 2026-09-01

Installed at `/opt/homebrew/bin/silicon-browser`, v0.25.5. Command surface
below taken from `--help`, not from memory.

```markdown
---
name: silicon-browser
binary: /opt/homebrew/bin/silicon-browser
summary: web pages, scrolling, screenshots, PDFs
---

Terminal-native browser automation, built for agents. Non-interactive, so
`Bash` reaches all of it. There is no MCP server and none is needed.

## The commands that matter

    open <url>              navigate
    snapshot                accessibility tree with @refs — how you READ a page
    click <sel|@ref>        click; @refs come from the last snapshot
    type / fill <sel> <txt> input
    scroll <dir> [px]       scroll (up/down/left/right)
    get text|html|url|title read values
    find role|text|label …  locate without a CSS selector
    screenshot [path]       image
    pdf <path>              save the page
    batch ["cmd" …]         several commands in one process
    close [--all]           end the session

## Reading a page — snapshot flags

    -i, --interactive   only interactive elements
    -c, --compact       drop empty structural nodes
    -d, --depth <n>     limit tree depth
    -s, --selector <s>  scope to a CSS selector

## Known failure mode (2026-07-16, cost ~$1.53)

A bare `snapshot` on an infinite-scroll page (x.com home timeline) can hang
indefinitely. macOS here has no `timeout`/`gtimeout` binary, so you cannot
wrap it. Instead:

- Always prefer `snapshot -i -c` on heavy pages. Add `-d <n>` or
  `-s <selector>` to scope to the container if still slow.
- If a call has not returned in ~30–60s, do not keep polling. Kill it, retry
  once narrower, and if it hangs again **stop** — write a one-line failure
  note and report it. Do not spend a turn budget monitoring a stuck command.

## Login and credentials

The tool has an `auth` vault (`auth save|login|list`). **Do not use it for
x.com.** Standing rule: that is Janhavi's real account — no credential
handling, human pace, no bursts. If a page is logged out or captcha-walled,
stop, write a one-line failure note, and ask her to log in once herself.
```

### `_tools/robot-io.md` — template, not yet installed

`robot-io` is **not installed** as of 2026-09-01: no module, nothing on PATH.
This card is a template; the command surface below comes from v1's shipped
skill file (recoverable at `git show 281ebc4^:prompts/skills/shared/robot-io.md`)
and must be re-verified against `--help` once installed.

```markdown
---
name: robot-io
binary: robot-io
summary: the arduino robot — 16x2 LCD face, servo hand, webcam, mic, speaker
install: pip install git+https://github.com/JanhaviDadhania/robot-io   # needs janhavi's yes
---

The physical body. Use it when a physical beat lands harder than text, or when
Janhavi asks you to look, listen, show or wave.

## The daemon

The daemon owns the serial port and **auto-starts** on first use — v1 shipped
the working robot with bismuth supervising nothing. Log at
`~/.robot-io/daemon.log`.

If you ever need to start it by hand, make it idempotent. Running this twice
must not produce two daemons fighting over the serial port:

    pgrep -f 'robot_io.daemon' >/dev/null || \
      nohup python3 -m robot_io.daemon >> ~/.robot-io/daemon.log 2>&1 &

Note `nohup … &`, not `setsid` — **macOS has no `setsid`**. This survives the
worker exiting, because the runtime kills only the worker's own process
(`v2/subagent.py`, a bare `proc.kill()`).

## Failure rule — the whole daemon strategy

Any body command errors: **drop the body this turn, reply in text, no apology,
no retries.** Same organ fails twice in a session: say so once, then stop using
it. Do not health-check the daemon; find out by trying, and shrug it off.

## Before re-flashing the Arduino

Stop `robot_io.daemon` before running `avrdude`, or port contention shows up as
bogus bootloader errors. (The original note also said to kill `harness.py`;
that was v1's harness and it no longer exists. `python3 -m v2 serve` does not
touch the serial port.)

## Face — 16x2 LCD

    face clear
    face text <row> <col> "..."      2 rows x 16 cols; retains until overwritten
    face char <slot> <8 bytes>       define a glyph
    face put <row> <col> <slot>      place it

Idle pose is the Wall-E eyes, slot 0. First body action of any turn: redraw
them — whatever the LCD held is stale. Restore them before ending the turn.

    face char 0 0E 11 15 15 11 0E 00 00
    face put 0 6 0
    face put 0 9 0

Glyphs: heart `00 0A 1F 1F 0E 04 00 00` · smile `00 11 11 00 11 0E 00 00` ·
sad `00 11 11 00 0E 11 00 00` · think `0E 11 15 15 0E 04 02 00` ·
sparkle `04 15 0E 1F 0E 15 04 00`

## Hand — one servo

`hand <angle>` blocks until done. **Always return to 90**; extremes strain the
servo. The hand is a tail — tiny twitches count.

    full wave    120 60 120 60 90
    tail-wag     100 80 100 80 90
    droop        30 --speed 30
    perk up      150 --speed 5
    think twitch 92 88 90

## Camera, mic, speaker

    cam snap --out /tmp/cam_<short>.jpg     always pass --out; then Read the image
    mic start --out /tmp/listen_<x>.wav     never unprompted — confirm she's ready
    mic stop                                then tools/transcribe.py, route as text
    speaker play <file>

180s hard cap on the mic; chunk start/stop if longer.

## Tone

Body = vibe, Telegram = info. The full answer goes to Telegram; the body picks
one detail, one word, one gesture. Never make LCD, voice and hand redundantly
say the same thing. TTS speaks **one** word — the fun one — not the sentence.
Default one sound per turn.

Reactive, not proactive: no scheduled body actions unless she asks for them.
```

---

## Long-running processes — no supervision, by evidence

Verified 2026-09-01 on this machine: a worker can start a process that outlives
it, today, with no code change.

- `v2/subagent.py` reaps with a bare `proc.kill()` — no `killpg`, no
  `start_new_session`. Only the `claude` process dies.
- `nohup <cmd> >> log 2>&1 &` survives the worker, a bismuth restart, and
  Ctrl+C on `run.sh`. Tested: a 10-tick child kept writing after its parent
  shell exited.
- **`setsid` does not exist on macOS.** Most detach recipes use it. Use
  `nohup`.

What this does *not* give: restart on crash, any record the process exists,
survival across reboot, or duplicate protection. Of those, only duplicates are
a real risk here — two daemons on one serial port — and a `pgrep -f … ||` guard
in the tool card fixes it with zero code.

**So no `_daemons/` folder and no supervisor.** v1 shipped the working robot —
personality pass, R2-D2 chirps, idle-eye tuning, weeks of commits — with the
daemon self-starting and bismuth oblivious. Adding supervision now would mean
bismuth racing robot-io for a port robot-io already manages.

If a tool ever appears that genuinely cannot self-start, the supervisor is
recoverable and already debugged: `git show 281ebc4^:harness.py`, lines
730–900. It carries details only bugs teach — a cmdline check before killing a
PID so a stale entry never kills an unrelated process, exponential backoff
(30s base, 30min cap) with a healthy-uptime reset, boot-time orphan
reconciliation, and a synthetic message to the agent after 3 consecutive
crashes.

---

## Architecture deltas

Changes to files that already exist. Everything else is new files.

1. **`destinations.py`** — add `or p.startswith("_")` to the skip predicate.
   Reserves `_schedules/`, `_tools/`, and anything future.
2. **`runtime.py` `_background`** — a 4th check, **and each of the four wrapped
   in its own `try/except` with a trace event.** Already a latent bug: one
   exception kills the thread and takes audio push, git sync and the board with
   it. `_schedules/` makes it a live one, since a hand-edited file can throw in
   `parse()`.
3. **`runtime.py` `process_turn`** — fold the tools fingerprint into the
   existing destinations fingerprint; one flag, not two.
4. **`state.py`** — `schedules` key in `default_state()`. Tier 1, tiny; losing
   it costs one duplicate run, never lost work.
5. **`mainagent.py` `build_turn_input`** — `TOOLS` block beside `DESTINATIONS`.
   The `kind == "system"` branch already renders the SYSTEM block; schedules
   need no change there.
6. **`intent_schema.json` / `intents.py`** — two new intents. Dispatch is
   `getattr(self, f"_do_{itype}")`, so it is two methods and two enum entries.
   No new intent for tools: adding a tool is an ordinary `spawn`.
7. **`main_agent.md`** — ~16 lines total across both parts. Both generic;
   neither names a specific schedule or tool. (Noted because the last three
   commits were cutting prompt lines, not adding them.)
8. **`tools/watchers/`** — delete. It survived the prune containing only
   `__pycache__`.

### Testing

There is no test suite, and `config.py` references `python3 -m v2.smoke`, which
does not exist. `feed` covers notes; nothing covers a SYSTEM turn. So **A9 is
required, not optional** — without `python3 -m v2 fire <name>`, the only way to
test a schedule is to wait until tomorrow morning.

`BISMUTH2_MEMORY_DIR` + `BISMUTH2_RUNTIME_DIR` point a whole v2 at a scratch
tree, so none of this needs to rehearse against real memory.

---

## Decisions this plan assumes — **all ten confirmed 2026-09-01** and logged in
`V2_REQUIREMENTS.md` under *Decisions — 2026-09-01 (schedules and the tool
catalog)*, with one amendment: #6's verification is **debounced** (see there).

1. Schedules and tools are **data in reserved memory folders**, never generated
   code. Nothing in `v2/` is edited to add one.
2. Reserved folders are `_`-prefixed and excluded from `DESTINATIONS` by a
   generic rule.
3. `last_fired` lives in `state.json`, written atomically with the enqueue.
4. A firing schedule carries a **pointer**, not its body.
5. Schedules fire **through the main agent**, not directly to a worker — so the
   work lands in the task projection and a dead worker still reaches her.
6. Artifact verification happens on the **next tick**, not at worker reap.
7. `schedule_create` always ships with a `reply` naming the cadence and the
   file. A schedule acts repeatedly while she is asleep; that message is her
   only window into what was written.
8. **No daemon supervision.** Idempotent `nohup` start lines in tool cards.
9. Tool cards are written by a **worker**; schedules are written by the
   **runtime**.
10. Installs require explicit confirmation on Telegram.

## Not building

- `_daemons/` and a process supervisor — see above.
- Cron expression syntax. `every: daily | weekly | n_days` plus `at:` covers
  everything Janhavi would say out loud, and nobody has to debug
  `0 30 8 * * *`.
- Watchers. Event-driven sensing stays out; polling schedules cover the real
  cases, and a genuine watcher would be an ordinary reviewed code task.
- A launchd job for bismuth itself. **Worth noting as the real gap:** nothing
  fires while the process is down. The date-guard catches up on next start, but
  a morning digest only lands most mornings if bismuth is actually running.

## Build order

**A1–A4** (the clock; testable with a throwaway schedule) → **A9** (`fire`) →
**A5–A7** (create by talking) → `produces` check → **A8** (board) → first real
schedule, `twitter-daily`, restored from v1's contract → **Part B** when
robot-io arrives.

~250 lines for A, ~100 for B.
