# Bismuth Code Writing Protocol

Basics Start

This protocol applies when Bismuth writes new code or updates its own code: harness, tools, watchers, and CLIs.

Occam's razor governs every change. Keep the simplest version that works.

Basics End

Structure Start

Code lives in `~/bismuth`. Personal data lives in `bismuth-memory`. Code must never contain personal data.

Bismuth must read the existing structure before writing.

New code must follow the structure that is already there.

Bismuth must not create a new file, folder, or tool when an existing one can be extended.

Bismuth must merge code when two files or tools grow to do the same job.

Structure End

Change Start

Bismuth should prefer small precise edits over rewrites.

Bismuth must not add features, options, or abstractions that are not needed now.

Bismuth must test a change before reporting it done.

Bismuth should remove dead code, but must ask Janhavi before deleting anything whose loss may matter.

Change End
