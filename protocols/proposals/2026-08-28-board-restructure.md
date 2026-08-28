# Proposal: the board restructure — slimmer Bismuth, one visual surface

**Observation:** 2026-08-28, janhavi dictated the v2 restructure (audio: `~/Desktop/niulai.m4a`).
The complaint driving it: the Telegram-only interface makes every answer a text block she has to
re-ask for, re-read, and scroll past. Chat is append-only, so nothing can be *seen at once*.
The fix is a board — one infinite canvas holding everything she and Bismuth are working on —
and a much smaller Bismuth around it.

Built on branch `board`: `tools/board.py`. The board and the merged next-todo panel are done.
The coffeechat removal from the harness is not — that lands with the slim harness.

---

## Built: `tools/board.py`

`python3 tools/board.py [--open]` → writes `{MEMORY_DIR}/board.html`, a self-contained
infinite canvas. Current run: **542 cards, 25 groups, 2.1 MB, no dependencies beyond stdlib.**

- One group box per project and per miniproject, on a single canvas, `PROJECTS` /
  `MINIPROJECTS` / `REMINDERS` as titled sections divided by rules — the layout she described.
- Card per thing: notes (`.md`/`.txt`) show a preview and open full text in a reading sheet;
  images render inline; short videos play inline; **long videos, big files, cloned repos and
  oversized folders become clickable links, never embedded payloads** — as instructed.
- Reminders render from `reminders.md` as month cards, colour-coded fired / overdue / today /
  future, merged into one panel with the home next todos. The text files stay the source of
  truth; the board is only a view of them.
- Pan, zoom-at-cursor, filter box, and drag-to-re-pin any card.

### Decisions made while building (implementation details, not open questions)

- **Works with the folder shapes that already exist.** She described a backend of
  `notes/ images/ videos/ files/` per project. Real projects instead have `reference/`,
  `coffeechat/`, `in_progress/`, `plans/`. The generator walks *whatever* is there and tags each
  card with its subfolder, so **no migration of 20 projects is needed**. Adopt the tidier shape
  later if wanted; the board does not care.
- **Vendored trees are hard-ignored.** A naive walk hits ~90k files (`node_modules`,
  `site-packages`, `.venv`). With the ignore list it is ~1.4k — hers.
- **Nested git repos collapse to one card.** Six do today (`novel/quartz`,
  `benchmark/theagentcompany`, the three `autoresearch` clones, `unicorn-bench`). Otherwise
  they alone would contribute thousands of cards.
- **Any folder over 40 files collapses to one card listing its file names** (each name a link),
  rather than a card per file. The CLI *prints every collapse* — a cap that is hidden reads as
  "the board shows everything" when it does not. Nothing in the tree hits this today; the
  biggest non-repo folder is `projects/artifacts/content/assets` at 44 files.
- **Layout is deterministic, and landscape by construction.** Same tree → same board, so cards
  never reshuffle under her between runs. Group column counts and the board width are chosen to
  pack close to a 1.8 aspect; the first attempt was a 6%-zoom vertical ribbon.
- **Empty projects still get a group** ("nothing pinned yet") rather than vanishing.

---

## Decided (janhavi, 2026-08-28) — no memory restructuring

**Next todos stay, exactly as they are.** Both `@janhavi` and `@agent` rows, home and per-project.
This closes the one item that would have broken a contract: `nexttodo.md` remains the executor's
input queue, so "run my tasks" keeps working untouched.

- Project and miniproject `nexttodo.md` files ride along with their own group on the board,
  as spine cards. Already the case.
- **Home `nexttodo.md` is merged with reminders into one panel** — section `NEXT TODO &
  REMINDERS`, one card per heading in the file, each row showing an owner chip (`janhavi` /
  `agent`) and struck through when done. Built.

**Coffeechat: remove the mode from the harness, leave the memory alone.** Every
`projects/*/coffeechat/` folder stays exactly as it is and keeps showing up as ordinary cards on
the board. The removal is `prompts/coffeechat.md`, protocols 06 + 14, `PROTOCOLS_BY_MODE`, and
the switching logic and session marker in `harness.py` — code only, no content touched.

**No restructuring of `bismuth-memory` for now.** How the tree should be shaped gets decided
while writing the slim harness, not before. The generator does not care either way — it walks
whatever is there.

## Feasibility verdict

Everything she asked for is feasible; the interface half is already done.

- **Voice in / text back over Telegram: already works.** `harness.py` downloads voice and audio
  messages and runs them through `tools/transcribe.py` (faster-whisper, on-laptop). Zero work
  for v1. The iPhone app can wait behind it without blocking anything.
- **The board: done**, subject to the two caveats below.

### Caveat A — the board cannot write back to memory  ⚠️

`board.html` is a static file opened over `file://`. It can *read* the memory tree, so dragging
a card persists in that browser's `localStorage` and survives reloads — but it cannot write into
`bismuth-memory/`. So hand-placed positions are **per-browser and invisible to Bismuth**, and a
new browser or cleared storage resets to the generated layout.

If she wants the board to be a real desk — arrange it once, Bismuth respects the arrangement,
positions committed to memory — that needs a tiny local server (~40 lines, `http.server`
POSTing a `board_layout.json`) instead of a bare file. Worth doing only if she finds herself
rearranging; the generated layout may be enough. This is also the fork in the road toward the
Mac app she floated.

### Caveat B — 542 cards means the zoomed-out board is a map, not a text you can read

Zoom-to-fit lands around 8–12%: section labels and group tints read fine, card text does not.
She predicted this ("maybe trim the details and then ask me to click on it to expand"). v1 shows
everything, per her instruction for version one. The obvious next step, when she has looked at
it: collapse each group to its spine cards plus a `+N more` chip that expands on click.

### Caveat C — voice is now the primary interface, and the transcription model is the weak link

`transcribe.py` defaults to faster-whisper **`base`**. On her own 8-minute dictation it produced
"many projects" for *mini projects*, "excalator" for *Excalidraw*, "MAT app" for *Mac app*, and
"next to do" for *nexttodo* — every one a term this system depends on. That was survivable
because a human read the transcript. For a voice-first Bismuth acting on what it hears, it is
not. Recommend defaulting to `small` (or `medium`), and adding a short domain vocabulary of
her recurring terms. Cheap change, large correctness gain.
