# Bismuth Project Creation Protocol

Basics Start

Bismuth should create a project when Janhavi asks it to create a project.

Bismuth should not create a new project from a passing mention.

Bismuth should not create a project when an existing project is a clear near-match.

Basics End

Creation Start

When creating a project, Bismuth must create:

- project folder under `projects/`
- `summary.md`
- `mood.md`
- `vision.md`
- `nexttodo.md`
- `reference/summary.md`
- `coffeechat/`

Bismuth should create `to_read.md` if the project has reading or research material.

Bismuth should add project context from Janhavi's original message into `vision.md`.

Bismuth should explain the new project in project `summary.md`.

Bismuth should update home `projects/projects_list.md`.

Bismuth should update home `summary.md`.

Bismuth should leave project creation tracking to the independent Python/runtime logging layer.

Creation End
