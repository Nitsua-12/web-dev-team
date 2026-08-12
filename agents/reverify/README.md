# Lead Re-verification Agent

A `qualified_no_website` lead discovered weeks ago might have a real site
by the time outreach actually happens. A `qualified_outdated` lead's site
might have been fixed. Without this, every downstream agent — the demo,
the outreach copy, the dossier — keeps arguing from stale facts. This
re-checks currently-active leads against Google and corrects `leads.db`
in place when reality has changed.

No LLM calls, same as Discovery itself — this is pure API + rule-based
classification, deterministic and cheap. It reuses Discovery's own
`places_client.py` and `site_check.py` directly (by file path, not
duplicated), so a re-check lands in exactly the same bucket a fresh
Discovery run would put it in — there's only one classification
implementation in this project, not two that could quietly drift apart.

## Running

```
python reverify.py --dry-run              # see what would change, save nothing
python reverify.py --limit 3               # smoke test
python reverify.py                          # full run
python reverify.py --min-days-since-check 0 # force-recheck everyone, ignore last-checked dates
```

Default `--min-days-since-check` is **7** — a lead checked within the
last week is skipped, so repeated runs naturally advance through the
backlog instead of re-spending API budget on leads just checked. Every
check is logged regardless of whether anything changed, dry-run included
— even a dry-run "uses up" that lead's staleness window, so testing
doesn't burn extra real API calls beyond the check itself.

## What actually happens on a change

For each currently-qualified lead: fetch its current `websiteUri` from
Google (one Place Details call, cheap), run it through Discovery's exact
same outdated-site heuristic, and compare the result to what `leads.db`
currently says. If they differ, `leads.db` is updated in place —
`website_url`, `has_website`, `website_status`, `qualification_status`,
the same fields every other agent reads. If a lead goes from
`qualified_outdated` to `disqualified_modern`, for example, it stops
showing up as an active lead for Outreach, Website Demo, or the Dossier
agent on their *next* run — automatically, correctly, no new stale demo
or draft gets generated for a problem that's already solved.

That's the forward-looking half. It does **not** reach back and touch
anything already generated — an `output/`, `drafts/`, or `dossiers/` file
written before the status changed keeps existing exactly as it was,
looking just as current as it did the day it was made. See "Known
limitations" below.

Any qualification-status change also resets the website-audit columns
(`audit_status`, `audit_score`, `audit_signals`, `audit_run_at`, added by
`agents/discovery/site_audit.py`) back to their unset defaults. A prior
audit reflects the lead's state at the time it ran — once reverify has
detected the underlying site actually changed, that audit is no longer
accurate and shouldn't sit around as if it were current evidence in an
Outreach or Dossier prompt. `main()` also ensures `leads.db` has these
columns at all (calling Discovery's own migration) before touching
anything, since reverify can run against a copy of `leads.db` that hasn't
had `discovery_agent.py` run against it recently — the two agents write to
the same file independently.

## Verified against real leads, including the case that actually matters

Not just "it runs without erroring" — tested the actual failure mode
this exists to prevent:

- Dry-run and live run against real leads → correctly reported no change
  (accurate — nothing has genuinely changed for these leads yet).
- The staleness filter → running immediately again correctly skipped the
  just-checked leads and moved to the next batch, confirming repeated
  runs won't waste budget re-checking the same leads.
- **The core case:** deliberately set a real lead's `qualification_status`
  wrong in `leads.db`, ran reverify, confirmed it correctly detected the
  mismatch against the live site and corrected it back to the true state
  — verified by reading `leads.db` afterward, not just trusting the
  script's own output.

## Known limitations

- **Doesn't touch anything already generated.** Correcting `leads.db`
  doesn't reach into `output/`, `drafts/`, or `dossiers/` — a demo, draft,
  or dossier written before a status change keeps sitting there looking
  current. Today that's a manual flag (a blockquote inserted near the top
  of the affected file) — see
  [../outreach/README.md](../outreach/README.md#a-draft-can-go-stale-after-its-generated)
  and [../discovery/README.md](../discovery/README.md#this-status-isnt-permanent)
  for the real example this happened to (Village Tattoo NYC) and what the
  flag actually looks like. Worth automating (have reverify write the flag
  itself, or have the affected agents check a lead's current status before
  trusting their own output) once this happens often enough to be worth
  building instead of doing by hand.
- **No connection to the scheduler** — if a lead's status flips to
  `disqualified_modern` after a follow-up was already scheduled, the
  scheduler will still compute it as due (it doesn't check current
  `qualification_status`, only suppression and replies — see
  [../scheduler/README.md](../scheduler/README.md#known-limitations)
  for the same gap documented from that side). Worth wiring together if
  this becomes a real problem in practice. (Suppression itself is
  correctly *not* part of this gap — an opt-out has to be honored
  regardless of a lead's qualification status, so it deliberately never
  checks it; that's by design, not a missing connection.)
- **No connection to outcomes** — already documented, and correctly so,
  from the other side: see
  [../outcomes/README.md](../outcomes/README.md#known-limitations)
  ("no connection to reverify"). If a lead's status changes after an
  outcome was already recorded, nothing reconciles the two. Same
  reasoning as the scheduler gap, judged lower-priority there since
  recording an outcome usually means the lead has left the active
  re-verification pool anyway.
- **Google Places API cost applies per check** — same billing tier as
  Discovery's original lookups (this reuses the same field). Running
  `--min-days-since-check 0` across a large lead volume repeatedly would
  add up; the default 7-day window exists specifically to control that.
- **No notification when something changes** — like the scheduler, this
  is pull, not push. A human has to run it and read the output; nothing
  proactively surfaces "3 leads got disqualified" anywhere else yet.
