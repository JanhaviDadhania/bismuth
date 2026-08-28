# skill: silicon-browser-web-actions
# scope: any task needing real browser actions on a logged-in site — esp. LinkedIn outreach — via the local `silicon-browser` CLI (on PATH at /opt/homebrew/bin/silicon-browser). Bismuth drives it directly via Bash.

A standalone local browser-automation CLI. It is SEPARATE from the Glass/Silicon "team of silicons" product — don't conflate them, and don't delegate browser work to a silicon; run it yourself. (An older note claiming bismuth couldn't run it and had to delegate was wrong; verified local and working 2026-06-30.)

## Core loop

1. `silicon-browser open <url>`
2. `silicon-browser snapshot` — accessibility tree with `[ref=eN]` handles
3. Act on a ref: `click @eN` / `fill @eN "text"` / `type @eN "text"` / `find role button "Send" click`
4. `get url|title|text` and re-snapshot to CONFIRM the action landed before reporting it.

Multi-step flows: snapshot between every step; never assume a click worked.

## LinkedIn

The browser persists a profile and janhavi's LinkedIn is logged in. If the session ever expires, ask her to log in once via the same browser — never handle credentials yourself.

Her outreach rules govern — automation does NOT override them. Material lives at `bismuth-memory/projects/find_a_job/` (tracker, per-person drafts, voice rules in the outreach `CLAUDE.md` — read those before touching any draft).

1. Drafts → show her → her explicit "go" per person → send. (Only skip the per-person ask if she explicitly says send them all.)
2. Eligibility filter and by-company-size targeting apply before adding anyone.
3. Check acceptances via her network / sent-invitations / the person's profile.
4. Follow-ups: open the connected person's thread, paste their post-connection draft, attach the resume where relevant.
5. Update the outreach tracker with status + date.

## Hard guardrails

- **Never** report sent / accepted / replied unless a post-action snapshot or `get` confirms it on screen. No bluffing — a fabricated "sent ✅" is the worst possible failure here.
- LinkedIn aggressively detects automation: human pace, small batches, no bursts. Checkpoint / captcha / "unusual activity" → STOP immediately and tell janhavi.
- It's her real personal account — when in doubt, show her before sending.
- **`--session-name`/`--session` does NOT isolate browser sessions — there is only ONE shared browser instance on this machine.** Confirmed live 2026-07-29: two concurrently-spawned executors (a Deliveroo application retry and a LinkedIn Berlin/Dubai job-search run), each told to use a different `--session-name`, ended up driving the same shared tab. Never spawn two silicon-browser executors at the same time — run browser-automation tasks strictly one-at-a-time (sequential executors, not parallel), even across different sites/projects (find_a_job applications, LinkedIn outreach, twitter digest all compete for the same one browser). If a task spec's "process" section claims `--session-name` gives isolation, that claim is wrong — strike it before spawning.
- **Long browser-automation executor runs are prone to dying mid-batch with `API Error: Connection closed mid-response`** (seen 2x by 2026-07-29, both on job-application batches 30-45+ turns deep). This is an infra flake, not a task-logic bug — no retry-workaround needed, just respawn. Mitigate the cost: scope each executor task to a small batch (2-3 applications/actions) rather than one long run covering many targets, so a mid-run death loses little and the task spec's own tracker file (updated incrementally, per completed item) preserves everything already confirmed. Always check the tracker file for what's already done before respawning a continuation — don't re-apply to the same company twice.
