# skill: silicon-browser-web-actions
# scope: any task needing real browser actions on a logged-in site — esp. LinkedIn outreach (check who accepted a request, send messages) but also any "go do X on a website" task. You have NO native browser tool; the silicons' silicon-browser is your only browser path.

## The correction this skill exists to make
Do NOT tell janhavi "I have no browser automation / you have to do it yourself." That's only half true. You (bismuth) have no native browser/computer-use tool — BUT the silicons (running in Docker under `~/silicons/<name>`) ship **`silicon-browser`**, a Steel **cloud-browser** automation you can drive via the silicon container. When a web action is needed, reach for that instead of punting to janhavi.

## The one real precondition (don't gloss over it)
silicon-browser drives a **cloud** browser (Steel), a *different* browser from janhavi's Mac. So "janhavi is logged into LinkedIn on her laptop" does NOT carry over — the cloud browser has none of her cookies. It only has a logged-in session for a site if a **browser profile** was set up for it:
- `silicon browser-profile setup <token>` — create a Steel profile through Glass (janhavi does a headed login into LinkedIn once).
- `silicon browser [name]` — open a headed browser for login.

A prompt/skill edit cannot conjure her session — the headed login is a one-time step **janhavi must do**. Until a LinkedIn-authenticated profile exists, you genuinely cannot act on LinkedIn; the blocker is the profile, not your self-awareness.

**REALITY — verified 2026-06-30 (corrects the optimistic framing above):**
- `silicon-browser` = `/opt/silicon-runtime/bin/silicon-browser`, a Steel-powered terminal browser (open/snapshot/click/fill/type/screenshot). It REQUIRES `STEEL_API_KEY`.
- **Bismuth CANNOT run it.** The Steel key is center-managed by Glass and never exposed ("secrets are not returned"); not in the container env for an ad-hoc `docker exec`. Confirmed: `silicon-browser install` → "STEEL_API_KEY is not set" on both silicons. Driving it from bismuth FAILS.
- The Steel key is injected only when a **silicon's own browser worker** runs (`/silicon/worker/handler.py`). The entity with browser access is the **silicon agent, not bismuth**.
- No LinkedIn profile/session exists on any silicon (`.silicon-browser` dirs empty, no cookie). Janhavi saying "I'm logged into LinkedIn there" did NOT persist to a silicon profile (likely she logged into her own Mac browser — unrelated to the cloud Steel browser).

**Correct path → DELEGATE to a silicon via the chat (interface.teamofsilicons.com), don't operate the browser from bismuth:**
1. Ask a silicon in chat to open a LinkedIn session — it uses `silicon-browser share` to return a remote-browser link where janhavi logs in once, then `profile save` persists it.
2. Task that silicon: "send connection requests / messages to these people with this note." It drives silicon-browser (it holds the Steel key) as janhavi's session.
This is what Silicon is for. Bismuth's role: prep the drafts/targets and hand them to the silicon.

## How to drive it
Entry points seen (confirm exact subcommands with `silicon-browser --help` inside the container, and the silicon-interface `browser`/`remote-browser <room> <url>` verbs):
- inside the container: `docker exec <silicon-container> silicon-browser ...` (binary) / the `silicon_browser` python pkg.
- silicon-interface: `si browser <room> <url> [--ttl 60]`, `si remote-browser <room> <url>`.
Driving a full multi-step LinkedIn flow (find status → open thread → type → send) is real automation, not a one-liner — confirm the action API before promising it works.

## LinkedIn outreach workflow (once a profile is live)
search_approach.md + the sarvam trackers still govern — automation does NOT override janhavi's rules:
1. **Drafts → show → her explicit "go" per person → send.** Unless janhavi explicitly says "send them all without asking," keep showing each before sending. The drafts live in `find_a_job/sarvam/outreach/<person>.md` and `find_a_job/drafts/outreach/`.
2. Eligibility filter (remote > India office > visa-sponsor) + by-company-size targeting still apply before adding anyone.
3. **Check acceptances:** navigate her LinkedIn network / sent-invitations / the person's profile; read connection status.
4. **Send the follow-up:** open the connected person's thread, paste their post-connection draft (resume + referral ask), attach `JanhaviDadhania_resume_SARVAM.pdf` where relevant.
5. **Update `find_a_job/sarvam/outreach_tracker.md`** statuses: `reached-linkedin` / `connected` / `replied`, with date.

## Hard guardrails
- **Never** report something as sent / accepted / replied unless silicon-browser actually confirms it on screen. Janhavi's #1 rule is no bluffing — a fabricated "sent it ✅" is the worst possible failure here.
- LinkedIn **aggressively detects automation**. Act human-paced, small batches, no bursts. If you hit a checkpoint / captcha / "unusual activity" warning, STOP immediately and tell janhavi — a restricted LinkedIn mid-job-search costs far more than the invites are worth.
- It's an **eval** silicon doing janhavi's personal outreach — fine since she asked, but keep the account-safety bar high.
