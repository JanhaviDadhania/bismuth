# Smoke corpus — bismuth v2

Step 10 of the build order: run these, verify, and only then trust it.

Two ways to run each one:

```sh
# offline — real agents, real workers, scratch tree, replies printed not sent
BISMUTH2_MEMORY_DIR=/tmp/memtest BISMUTH2_RUNTIME_DIR=/tmp/rttest \
  python3 -m v2 feed "<the message>"

# live — say it into Telegram with `python3 -m v2 serve` running
```

After each, check three places: `python3 -m v2 status`, the trace
(`~/bismuth-memory/trace/log-YYYY-MM.jsonl`), and the file that should have
changed. The board (`open ~/bismuth-memory/board.html`) refreshes every 2 min.

| # | Say | Expect |
|---|---|---|
| 1 | "this is regarding the mirror. add a next todo to collect collage refs" | `route_decided` mode=declared → worker writes → `ack` status=saved. **No Telegram reply** — filing is not news |
| 2 | "for sheldon, next todo: pull the psychohistory quotes" | routed to `projects/seldon/` — mangled transcription recovered |
| 3 | "put this in my quantum gardening project: …" | `route_rejected` → `parked_in_others` → **then** a question. Check the trace order: parking comes first |
| 4 | answer #3 with a real folder | `task_clarified` → worker → `task_done` → she is told, `others/` empty |
| 5 | "what did I say about collage refs, and where is it" | a `kind: search` worker, answer quotes the line **with its path** |
| 6 | "what are you working on" | answered from the injected TASKS block, no worker needed |
| 7 | send a note, then `kill -9` the runtime mid-write, restart | boot reconciliation marks the worker failed, task returns to `unclear`, **she is told** |
| 8 | send something unreadable (a sticker) | parked and surfaced — never silently dropped |
| 9 | 3 notes in 10 seconds | one turn each, in order, no batching, nothing lost |
| 10 | let it run past 40% of the window | `session_reset reason=context_40pct`, and the task list survives it |

**The property under test in all of them is the same one:** nothing she says is
lost, and every failure is visible somewhere she looks. A message may fail; it
may not fail quietly.

```sh
python3 -m pytest tests/ -q          # unit tests — no money spent
```
