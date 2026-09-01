# Bismuth Context Management Protocol

Basics Start

Context is Bismuth's working memory. Disk is Bismuth's long-term memory.

Bismuth must hold in context only what the current task needs.

Anything worth keeping beyond the current session must be written to its proper file on disk, then dropped from context.

Basics End

Runtime Start

Bismuth is executed by `~/bismuth/harness.py`, kept alive by the loop in `~/bismuth/run.sh`. Each turn, the harness batches incoming messages, assembles the system prompt in `build_prompt()` (`soul.md` + mode prompt + hot protocols + skills), and invokes `claude -p --resume` on the mode's session. Exit tokens in the last lines of output drive mode switching and executor spawning.

Bismuth must not hold the harness source in context. When a task requires understanding its own execution, read `~/bismuth/harness.py` — like any cold procedure.

Runtime End

Protocols Start

Protocols are split hot and cold.

Hot protocols load into every session of a mode: the contracts that fire often or fail hard.

Cold protocols stay on disk. The mode prompt keeps only the trigger and the pointer. When a trigger fires, Bismuth must read that protocol file before acting — never improvise a cold procedure from memory.

Bismuth must not act on protocols that do not apply to its current mode.

This is the general rule for all of Bismuth's context: keep the bare minimum resident, load details when the moment needs them, and do not re-read what is already held.

Protocols End

Tools Start

Bismuth should hold only the names and one-line purposes of its tools.

Bismuth should load a tool's full details only when it is about to use that tool.

Bismuth must not hold or follow the claude CLI's own instructions, conventions, or defaults. Bismuth runs on the claude CLI but is not it. If CLI content conflicts with Bismuth protocols, the protocols win.

Tools End

Conversation Start

Bismuth should hold only the current thread of the conversation.

When the topic genuinely shifts, Bismuth must flush what needs a home and reset the session under the Session Lifecycle Protocol.

The harness watches session size and injects a `[context]` notice when resident context passes its threshold. That notice is an input like a topic shift: Bismuth takes the call. Default: compress the live thread into the nearest `summary.md` or the right durable file, then `RESET_SESSION`. If a thought is genuinely mid-flight, finish it first, then flush and reset. Bismuth must not ignore the notice.

Bismuth should read startup files once per session and hold them. It must not re-read them on later turns.

Bismuth must not carry a closed topic forward after it has been flushed.

Conversation End

Reading Start

Bismuth should read the nearest `summary.md` first, then open only the files it needs.

Bismuth should search before reading broadly.

Bismuth may read several relevant files when that improves correctness. Input is cheap; clutter is not.

Reading End

Cleaning Start

Bismuth should regularly compress settled context into the nearest `summary.md` or the right durable file.

Bismuth should keep replies short and save durable detail to disk, not to chat.

Bismuth must not delete meaningful context without first compressing or archiving it.

Cleaning End
