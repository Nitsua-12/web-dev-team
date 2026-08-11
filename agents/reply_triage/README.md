# Reply Triage

There is no live inbox or SMS line connected to this system — sending
doesn't exist yet, so nothing can watch for replies automatically. This
tool is what a human runs the moment they personally see a reply, in
their own email client or phone: it gets Claude's read on what the reply
actually means and reacts appropriately.

## Why this exists

Flagged in [ARCHITECTURE.md](../../ARCHITECTURE.md) §19 as a role that
was necessary but not named in the original brief: something has to
notice a lead replied and connect it to the "human takes over" step. This
is that connective tissue — not a live monitor (there's nothing to
monitor yet), but the classification and action logic that a real
inbox/SMS integration would eventually call automatically.

## Running

```
python triage_cli.py --business "Village Tattoo NYC" --channel sms --text "Reply STOP"
python triage_cli.py --phone "917-500-8489" --channel email --text "Sure, send it over!"
python triage_cli.py --business "Some Shop" --channel phone_call --text "Owner said they're not interested right now, call back in a few months"
```

`--channel phone_call` exists for exactly that last example — replies
don't only arrive in writing; a human can log a phone conversation the
same way by typing a summary of what was said.

## What it does

1. Looks up the lead in `../discovery/leads.db` by business name or phone
2. Classifies the reply with Claude into exactly one of: `opt_out`,
   `interested`, `not_interested`, `question`, `unclear`
3. Takes action based on the classification:
   - **opt_out** → automatically adds the lead's phone to
     [the suppression list](../suppression) (reason depends on channel:
     `stop_reply` for SMS, `unsubscribe` for email, `manual` for a
     logged call) — no human step required, this happens immediately
   - **interested** / **question** / **unclear** → writes a clearly
     marked "NEW REPLY — ACTION NEEDED" section directly into that
     lead's `dossier.md`, right after the header, so it's the first
     thing visible when the file is opened. Multiple replies stack,
     newest on top.
   - **not_interested** → logged, but *not* auto-suppressed — declining
     right now isn't a legal opt-out, so this is a human judgment call
     about whether to stop following up, not an automatic one
4. Logs every reply to its own `replies.db` (independent of `leads.db`,
   same reasoning as the suppression list — a communication record
   shouldn't be at risk if lead data gets rebuilt)

## Verified against real leads

Tested both branches end-to-end, not just individually:

- **Interested reply** on Village Tattoo NYC → correctly classified,
  correctly flagged in that lead's real dossier.
- **Opt-out reply** on a lead with no phone on file (Unique Ink Tattoos
  NYC — Google's listing genuinely has no phone for them) → correctly
  classified, correctly reported it *couldn't* suppress rather than
  silently doing nothing or crashing.
- **Opt-out reply** on a lead with a real phone (Village Tattoo NYC) →
  correctly classified, correctly added `+12124753708` to the
  suppression list with the right reason and source.

All test data (suppression entries, dossier edits, reply log rows) was
removed after verification — nothing in this repo's state reflects fake
activity.

## Known limitations

- **No automatic trigger.** This only runs when a human decides to run
  it. The role described in ARCHITECTURE.md §19 as "notices a lead
  replied" isn't automated yet — a human still has to notice the reply
  in the first place, then choose to log it here.
- **Exact business-name match required** for `--business` lookup (case
  insensitive, but no fuzzy matching) — use `--phone` if the name isn't
  exact.
- **`not_interested` has no automatic suppression**, by design, but also
  no automatic "pause follow-ups" action either — right now that's
  purely informational until a human acts on it.
- **Anthropic API reliability:** during testing, this hit a genuine
  multi-minute `529 Overloaded` stretch from Anthropic's servers (a
  known, confirmed event — Anthropic has had global outages with this
  exact error before). The SDK's built-in retries didn't cover an outage
  that long; a production version of this tool should have its own
  longer backoff/retry loop rather than failing outright during a
  provider-side incident.
