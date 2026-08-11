# Suppression List

Tracks opt-outs so this system can never contact someone who's said stop.
This exists as its own agent — not a table in Discovery's `leads.db` —
deliberately: a suppression must persist independently of the lead
lifecycle. If `leads.db` ever gets rebuilt, pruned, or a lead record
changes, the fact that someone opted out must never be lost with it.

No API keys, no pip dependencies — this is pure Python standard library
(`sqlite3`, `argparse`) touching one local file, `suppression.db`.

## Why this exists

CAN-SPAM (email) and TCPA (SMS) — both referenced throughout this
project's other READMEs — require honoring opt-outs, and TCPA in
particular treats this as an ongoing obligation, not a one-time courtesy.
This was flagged in [ARCHITECTURE.md](../../ARCHITECTURE.md) §19 as the
one piece worth building *before* any sending capability exists, because
it shapes how that system has to work rather than being something you
bolt on after the fact.

## Current scope: phone only, and here's why

Discovery captures a lead's phone number from Google's business listing,
but **not an email address** — Google Places API doesn't return one. So
right now, there is no email data flowing through this pipeline for the
Outreach agent's "email" draft to actually be sent to. The schema here
supports both `phone` and `email` contact types for whenever an email
source gets added, but the only real, wired-up integration today checks
**phone**, because that's the only contact channel with real data.

## Running

```
# Record an opt-out (usually a human doing this after a call or reply)
python suppression_cli.py add --phone "(212) 555-0100" --reason manual --source phone_call --notes "asked us to stop during a call"
python suppression_cli.py add --email jane@shop.com --reason unsubscribe --source email_reply

# Check before you would otherwise contact someone
python suppression_cli.py check --phone "212-555-0100"

# See everything on the list
python suppression_cli.py list

# Fix a mistaken entry (not for routine use)
python suppression_cli.py remove --phone "212-555-0100"
```

Valid `--reason` values: `unsubscribe`, `stop_reply`, `manual`, `bounce`,
`legal_request`. Phone numbers are normalized to E.164 (`+1XXXXXXXXXX`);
emails are lowercased and trimmed — so `check`/`add`/`remove` all match
regardless of how the number or address was originally formatted.

## Current integration

**[Outreach Copywriting](../outreach)** checks this list before drafting
anything for a lead. If a lead's phone is suppressed, no draft is written
and — just as importantly — no Anthropic API call is made for that lead
either. Verified against a real lead: added a test suppression, confirmed
the agent skipped drafting for that lead with a clear log line, then
removed the test entry.

## The integration that actually matters (not yet built)

This list being checked by Outreach is good practice, but the **hard
requirement** is that the eventual Sending agent (§16 in
[ARCHITECTURE.md](../../ARCHITECTURE.md), not yet built) checks this list
as a non-negotiable gate before every single send — email or SMS. That
integration doesn't exist yet because sending doesn't exist yet. When it
does, this should be one of the first things wired in, not an
afterthought.

## Known limitations

- No automated way to detect a "STOP" SMS reply or an email unsubscribe
  click and add it here automatically — that requires the reply-triage
  role described in ARCHITECTURE.md §19, which also doesn't exist yet.
  Until then, every entry here is added by a human, by hand.
- Phone-only in practice, per the scope note above — the `email` contact
  type is schema-ready but has nothing feeding it yet.
- No audit trail beyond `added_at`/`source`/`notes` on each row — fine at
  current scale, worth revisiting if this ever needs to answer "prove you
  honored this opt-out" in a legal context.
