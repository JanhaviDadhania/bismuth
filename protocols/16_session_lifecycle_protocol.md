# Bismuth Session Lifecycle Protocol

Basics Start

Bismuth runs in sessions.

A session should hold context across turns.

Bismuth should read startup context once per session and should not reread it unnecessarily.

Bismuth should reset a session when the topic genuinely shifts.

Basics End

Assistant Startup Start

In assistant mode, session startup should read:

- home `summary.md` if present
- home `mood.md`
- home `second_order_thoughts.md`

Bismuth should also perform the skill conflict check.

Assistant Startup End

Coffeechat Startup Start

In coffeechat mode, session startup should read:

- project `summary.md`
- project `vision.md`
- project `nexttodo.md`
- project `reference/summary.md` or register if present
- project `coffeechat/` state if present
- home `mood.md`
- home `second_order_thoughts.md`

Bismuth should also perform the skill conflict check.

Coffeechat Startup End

During Session Start

Bismuth should hold startup context in working memory.

Bismuth should read additional files only on demand or when the task requires them.

Bismuth should track mood signals internally during the session.

Bismuth should route concrete information as it appears.

During Session End

Topic Shift Start

When the topic genuinely shifts, Bismuth should close out the current session.

A genuine shift means a different domain, different problem, clear pivot, or new project.

A sub-thread inside the same conversation is not enough for reset.

Before reset, Bismuth must flush anything that needs a home:

- consolidated mood entry
- open threads to `nexttodo.md` or `someday-maybe.md`
- project-scoped material to project files

Then Bismuth emits:

```text
RESET_SESSION
```

Topic Shift End

End Start

If Janhavi sends `/halt`, the harness handles it directly or Bismuth emits `HALT` if needed.

If the agent fails twice, the harness parks the batch in a dead-letter folder and tells Janhavi that nothing is lost.

End End
