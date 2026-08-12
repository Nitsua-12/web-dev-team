# Follow-up Scheduler

Outreach drafts follow-ups with day offsets ("day 4", "day 17"), but has
no idea when — or whether — anything actually got sent, because sending
doesn't exist in this system yet. This tool closes that gap: a human
records what they actually sent (`mark-sent`), and it computes what's due
next, anchored to the real send date.

No API keys, no pip dependencies — pure Python standard library, same as
[suppression](../suppression). It reuses `suppression`'s and
`reply_triage`'s `db.py` modules directly (via explicit file-path
imports, since several sibling folders each have their own `db.py`) —
loose coupling on disk, no shared package, consistent with how every
other agent in this project talks to the others.

## Running

```
# Record what you actually sent
python scheduler_cli.py mark-sent --business "Village Tattoo NYC" --channel email
python scheduler_cli.py mark-sent --business "Village Tattoo NYC" --followup 1 --date 2026-08-05

# What needs to go out today (including anything overdue)
python scheduler_cli.py due

# What's coming up in the next week
python scheduler_cli.py upcoming --days 7
```

`--followup 0` (the default) is the initial send — every day_offset is
computed relative to that date, per the Outreach agent's schema, not
relative to whenever the previous follow-up went out.

## Why a lead can be sent-but-never-due

This only works for leads whose Outreach draft has a `draft.json`
sidecar (added specifically for this — see
[../outreach/README.md](../outreach/README.md)). A lead is silently
skipped from `due`/`upcoming` if:

- **It's on the [suppression list](../suppression).** Checked by phone
  every time — an opt-out stops all future contact, follow-ups included,
  permanently.
- **Any reply has been logged** in [reply_triage](../reply_triage)'s
  log, regardless of what the reply said. Once a real conversation has
  started, automated follow-ups should stop — even a `not_interested`
  reply means a human is now the one deciding what happens next, not a
  schedule.
- **No `draft.json` exists** for that lead — nothing to compute a
  schedule from.
- **All follow-ups already sent** — nothing left to schedule.

That's the complete list — notably, **a lead's current `qualification_status`
is not one of these checks.** If [reverify](../reverify) moves a lead to
`needs_review` or `disqualified_modern` after a follow-up was already
scheduled, this tool has no idea and will still compute it as due. See
Known Limitations below.

## Verified against real leads, all four branches

Not just the happy path — tested the scenario that actually matters,
which is *not* showing up in the schedule:

- A lead sent today → correctly excluded from `due`, correctly shown in
  `upcoming --days 7` with the right day count.
- A lead backdated 10 days → correctly shown as **OVERDUE** in both
  `due` and `upcoming`.
- A lead marked sent, then suppressed → correctly absent from both.
- A lead marked sent, then given a logged reply → correctly absent from
  both.

All test sends, the test suppression entry, and the test reply were
removed after verification.

## Known limitations

- **No connection to reverify.** `due`/`upcoming` only check suppression
  and reply state (above) — never `qualification_status`. A lead that
  [reverify](../reverify) has since flagged `needs_review` or corrected to
  `disqualified_modern` still shows up as due for its next follow-up here,
  exactly as if nothing changed. Already flagged from the other side in
  [../reverify/README.md](../reverify/README.md#known-limitations); worth
  wiring together (checking current `qualification_status` here, the same
  way suppression and replies are already checked) if this becomes a real
  problem rather than a theoretical one.
- **Doesn't send anything.** This computes and displays what's due; a
  human still has to actually send it and then run `mark-sent` for the
  next follow-up index themselves. That two-step (see it's due, go send
  it, come back and record it) is manual by design, matching everything
  else in this project until real sending exists.
- **No reminder/notification** — `due` and `upcoming` are pull, not
  push. Nothing proactively tells a human to run this command. That's
  the kind of thing the eventual orchestration layer (Temporal, per
  [ARCHITECTURE.md](../../ARCHITECTURE.md) §6) would handle — a daily
  scheduled job that runs `due` and surfaces the result somewhere a
  human will actually see it.
- **`--business` requires an exact match** (case-insensitive), same
  limitation as reply_triage's lookup — use `--phone` if unsure of exact
  spelling.
