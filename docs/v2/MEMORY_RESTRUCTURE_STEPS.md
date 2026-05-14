# Memory restructure — manual checklist

Two locations, mirror every change in both:

- `~/bismuth/memory/` — template (committed, sparse).
- `~/bismuth-memory/` — actual personal data. **Be careful, do not lose content.**

For destructive steps: always read non-empty files before deleting and confirm content has been folded into its new home.

**Rule:** anything custom inside a project directory is intentional — leave it alone unless explicitly listed below.

Target shape:

```
memory/
  nexttodo.md
  someday-maybe.md
  to_read.md
  mood.md
  second_order_thoughts.md
  tracking.md            # global, tagged <project:NAME>...</project:NAME>
  checklists.md          # kept (out-of-spec but useful)
  reference/
  projects/
    <project_name>/
      vision.md          # absorbs lore.md under "## History of the project"
      nexttodo.md        # merged agents_nexttodo.md + nexttodo.md
      to_read.md         # stays per-project (only if present)
      reference/         # renamed from support/
      ... (any other custom files/folders stay)
```

Tag syntax for global tracking.md / someday-maybe.md: `<project:NAME> ... </project:NAME>` (pending final confirm).

---

## Step 1 — Root-level (both template and actual)

### 1a. Rename `deferred-todo.md` → `someday-maybe.md`
- Both locations. Content preserved.

### 1b. Merge `agents_nexttodo.md` into `nexttodo.md`
- Tag rows that came from `agents_nexttodo.md` with `@agent`; existing rows are `@janhavi` (default).
- Delete `agents_nexttodo.md` after merge verified.

### 1c. Rename `MOOD.md` → `mood.md`
- Lowercase. Actual only (template doesn't have one — create empty).

### 1d. Rename `second_order.md` → `second_order_thoughts.md`
- Actual only (template doesn't have one — create empty).

### 1e. Move `capture/` contents into `reference/`
- Actual: move `01_DIR 2jhanvi.docx`, `03_Circular Jhanvi.docx`, `photo_36.jpg`, `photo_66.jpg`, `photo_82.jpg` → `reference/`.
- Template: move `photo_36.jpg` → `reference/`.
- Delete the now-empty `capture/` folder.

### 1f. Delete `plans/mood_and_second_order` (actual only)
- Confirmed by janhavi.

### 1g. Delete root cruft (read content first, fold anything meaningful)
- `pending_questions.md` — actual 21 bytes, likely empty stub. Read → delete.
- `running_agents.md` — empty. Delete.
- `delegate.md` — actual 98 bytes. **Read content, fold any real items into `nexttodo.md` with `@agent` tag, then delete.**
- `capture.md` — template only (1 byte). Delete.

### 1h. Delete `agents_nexttodo.md` (after 1b)

### 1i. Merge root `support/` into root `reference/`
- Move all PDFs/docs from `support/` into `reference/`.
- Merge `support/register.md` content into `reference/register.md` (append; keep both sets of entries; preserve as a directory summary).
- Delete the now-empty `support/` folder.
- Rule confirmed: every `reference/` keeps its `register.md` as the directory summary for searchability.

### 1j. Keep as-is at root
- `tracking.md`, `to_read.md`, `checklists.md`, `reference/` (now expanded), `projects/`, `areas/`, `config.yaml` (the memory-local one), `telegram_offset*.json`, `.git/`.

---

## Step 2 — Per-project restructure (actual only; template projects are skeletons)

Project list (actual): `ai_neuroscience`, `carousee`, `find_a_job`, `nostayidiot`, `people`, `seldon`, `social_media`, `software_design_studio`, `the_mirror`.

For each project:

### 2a. Merge `agents_nexttodo.md` + `nexttodo.md` → `nexttodo.md`
- Tag rows `@agent` / `@janhavi`. Delete `agents_nexttodo.md` after.

### 2b. Fold `lore.md` into `vision.md`
- Append into `vision.md` under a new section: `## History of the project`.
- Delete `lore.md` after fold verified.
- Affected: `ai_neuroscience`, `nostayidiot`, `people`, `social_media`, `the_mirror`.

### 2c. Fold `tracking.md` → global `tracking.md`
- Wrap content with `<project:NAME>...</project:NAME>` and append to global `tracking.md`.
- Delete per-project `tracking.md` after merge.
- Affected: `ai_neuroscience`, `find_a_job`, `nostayidiot`, `people`, `social_media`, `the_mirror`.

### 2d. Fold `deferred-todo.md` → global `someday-maybe.md`
- Wrap with `<project:NAME>...</project:NAME>` and append.
- Delete per-project after merge.
- Affected: `ai_neuroscience`, `nostayidiot`, `social_media`, `software_design_studio`.

### 2e. Rename `support/` → `reference/`

### 2f. Keep per-project `to_read.md` in place (do not fold to global).

### 2g. Delete `pending_questions.md`, `running_agents.md` (per project)
- Read first. If non-empty, fold any real items into project `nexttodo.md`.

### 2h. Coffeechat phase folders
- Projects with `coffeechat/{definition,outcome,brainstorm,organisation}.md`: leave the folder for now — v2 coffeechat agent will decide whether to keep or fold during its first pass on each project.
- (Earlier plan was to fold into `vision.md`. With the rule "anything custom stays," this becomes the coffeechat agent's job, not ours.)

### 2i. Leave everything else alone (custom = intentional)
- `the_mirror/in_progress/`, `the_mirror/plans/`, `the_mirror/how_i_write.md`
- `software_design_studio/calendar.md` — explicitly leave for later.
- `ai_neuroscience/neel_nanda_notes.md`
- `people/support.md`
- Any other per-project files/folders not named in 2a–2g.

---

## Step 3 — Template (`bismuth/memory/`)

Only mirror the structural changes. Keep template lean:

- Apply Step 1a–1h to template where applicable.
- Template projects (`ai_neuroscience`, `carousee`, `find_a_job`, `seldon`, `social_media`, `the_mirror`) stay limited to scaffold files: empty `vision.md`, empty `nexttodo.md`, empty `reference/` folder.
- Do not add `nostayidiot`, `people`, `software_design_studio` to template — those are janhavi-specific.
- Create empty seeds at template root for any spec'd file missing: `mood.md`, `second_order_thoughts.md`, `someday-maybe.md`, `to_read.md`, `checklists.md`.

---

## Open items before executing destructive steps

1. **Tag syntax** — going with `<project:seldon>...</project:seldon>` unless you say otherwise.
2. **`delegate.md` content** — I'll read first; if it has real entries I'll show you before folding/deleting.
3. **Root `support/`** (actual, has scanned PDFs) — leaving untouched; OK?
