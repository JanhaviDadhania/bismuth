# skill: silicon-browser-web-actions
# scope: any task needing real browser actions on a logged-in site — esp. LinkedIn outreach (check who accepted a request, send messages) but also any "go do X on a website" task. Bismuth drives the local `silicon-browser` CLI directly.

## What silicon-browser actually is (verified 2026-06-30, corrects the old note)
`silicon-browser` is installed **locally on janhavi's Mac** at `/opt/homebrew/bin/silicon-browser` (on PATH, v0.25.5). It is a standalone, fast browser-automation CLI for AI agents — `open / snapshot / click / fill / type / screenshot / get / find / eval`, etc. **Bismuth runs it directly via Bash. No Docker, no Steel key, no delegation to any silicon.**

This is a SEPARATE thing from the Glass/Silicon "team of silicons" product. The teams may also use a browser tool, but that has nothing to do with this local binary. Don't conflate them. The old version of this skill wrongly claimed bismuth couldn't run it and had to hand off to a silicon agent — that was wrong. Verified working: `silicon-browser open https://example.com` → succeeds, `snapshot` returns the a11y tree.

## LinkedIn session — already logged in
The local browser persists a profile, and **janhavi's LinkedIn is already logged in** (verified: `silicon-browser open https://www.linkedin.com/feed/` lands on the authenticated feed, not the login wall). So you can act on LinkedIn right away — no setup step, no headed login required. If a session ever expires, ask janhavi to log in once via the same browser; don't try to handle credentials yourself.

## How to drive it
Always full path or bare `silicon-browser` (it's on PATH). Core loop for any action:
1. `silicon-browser open <url>` — navigate.
2. `silicon-browser snapshot` — get the accessibility tree with `[ref=eN]` handles.
3. Act on a ref: `silicon-browser click @e12`, `silicon-browser fill @e12 "text"`, `silicon-browser type @e12 "text"`, `silicon-browser find role button "Send" click`.
4. `silicon-browser get url|title|text` and re-`snapshot` to CONFIRM the action landed before reporting it.
Driving a full LinkedIn flow (find connection status → open thread → type → send) is multi-step; snapshot between every step, never assume a click worked.

## LinkedIn outreach workflow
Janhavi's outreach rules govern — automation does NOT override them. The material lives at `bismuth-memory/projects/find_a_job/` (NOT directly under bismuth-memory). Active project: Sarvam — tracker `projects/find_a_job/sarvam/outreach_tracker.md`, per-person drafts `projects/find_a_job/sarvam/outreach/<name>.md`, voice rules `projects/find_a_job/sarvam/outreach/CLAUDE.md` (read before touching any draft), resume `projects/find_a_job/drafts/JanhaviDadhania_resume.pdf`. Workflow:
1. **Drafts → show → her explicit "go" per person → send.** Unless janhavi explicitly says "send them all without asking," keep showing each before sending. The drafts live in `find_a_job/sarvam/outreach/<person>.md` and `find_a_job/drafts/outreach/`.
2. Eligibility filter (remote > India office > visa-sponsor) + by-company-size targeting still apply before adding anyone.
3. **Check acceptances:** navigate her LinkedIn network / sent-invitations / the person's profile; read connection status.
4. **Send the follow-up:** open the connected person's thread, paste their post-connection draft (resume + referral ask), attach `JanhaviDadhania_resume_SARVAM.pdf` where relevant.
5. **Update `find_a_job/sarvam/outreach_tracker.md`** statuses: `reached-linkedin` / `connected` / `replied`, with date.

## Hard guardrails
- **Never** report something as sent / accepted / replied unless a post-action `snapshot`/`get` actually confirms it on screen. Janhavi's #1 rule is no bluffing — a fabricated "sent it ✅" is the worst possible failure here.
- LinkedIn **aggressively detects automation**. Act human-paced, small batches, no bursts. If you hit a checkpoint / captcha / "unusual activity" warning, STOP immediately and tell janhavi — a restricted LinkedIn mid-job-search costs far more than the invites are worth.
- It's janhavi's real personal LinkedIn account — keep the account-safety bar high. When in doubt, show her before sending.
