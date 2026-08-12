# Outreach Copywriting Agent

Drafts personalized outreach copy per qualified lead: initial email
(subject + body), SMS version, and two follow-up emails with a schedule.
Uses Claude (`claude-sonnet-5`) with structured outputs so the response is
always valid, parseable JSON.

**This agent cannot send anything.** There is no email or SMS integration
anywhere in this code — it only writes markdown files to `drafts/` for a
human to read, edit, and approve. Sending is a separate, not-yet-built
capability, and building it should be a deliberate later decision, not a
side effect of adding a "send" flag here.

## Running

```
python generate_drafts.py                # every qualified lead
python generate_drafts.py --limit 3        # smoke test on the first 3
python generate_drafts.py --force          # regenerate drafts that already exist
```

Reads from `../discovery/leads.db` by default. Output lands in
`drafts/<slug>/draft.md`, one file per lead. Re-running is safe — existing
drafts are skipped unless you pass `--force`.

Cost note: `claude-sonnet-5` at intro pricing ($2/$10 per million tokens
through 2026-08-31) — each draft is roughly 1-2K output tokens, so this is
cheap even at hundreds of leads. Chosen over the default `claude-opus-5`
specifically because bulk templated marketing copy doesn't need Opus-tier
reasoning; re-evaluate if draft quality doesn't hold up at scale.

## What's in a draft

Every `draft.md` has: the initial email (subject + body), an SMS version,
and two follow-up emails with day offsets (typically ~day 4 and ~day 16-18,
though the model picks realistic spacing per lead). Every email and the SMS
end with literal `{{TOKEN}}` placeholders — `{{SENDER_NAME}}`,
`{{SENDER_COMPANY}}`, `{{SENDER_PHYSICAL_ADDRESS}}`, `{{UNSUBSCRIBE_LINK}}`
— that a human must fill in before anything is sent. The agent doesn't know
your business's real name, address, or unsubscribe mechanism, and
fabricating them would be worse than leaving them blank.

Also referenced (but you'll need to fill in for real): a demo site link.
The current [Website Demo Generation agent](../website_demo) produces
local files, not a hosted URL, so the copy deliberately describes the demo
in words ("I put together a concept for what a modern site could look
like") rather than linking to something that doesn't resolve yet. Once
demos are actually hosted somewhere, this agent should be updated to
reference a real `{{DEMO_LINK}}` token.

## A draft can go stale after it's generated

`generate_drafts.py` only ever processes leads with `qualification_status`
`qualified_no_website` or `qualified_outdated` — a lead that
[reverify](../reverify) has since moved to `needs_review` or
`disqualified_modern` (site got fixed, or turned out to be inaccessible to
automated checks) is automatically excluded from any future run. That part
is enforced by the code, not just a convention.

What isn't automated: an **existing** `draft.md`, generated before the
status changed, doesn't know anything happened. Reverify corrects
`leads.db`; it has no mechanism to reach into `drafts/` and update or flag
a file that already exists. If a lead's status changes after its draft was
already written, that draft keeps sitting there looking exactly as
confident and ready-to-send as it did before — nothing in this pipeline
currently stops a human from sending it anyway.

Until something more automated exists, the practice is a manual flag: a
`> **DO NOT SEND — LEAD STATUS CHANGED (date).**` blockquote inserted right
after the draft's `**Qualification:**` line, explaining what changed and
pointing to the full story in that lead's dossier. See
`drafts/village-tattoo-nyc-new-york/draft.md` for a real example — that
lead's site started returning a bot-block to the automated checker, turned
out on manual inspection to be a real, currently-live, HTTPS site (not the
outdated one the draft was written against), and got flagged this way
rather than silently left to look current.

## Legal considerations — read before this goes anywhere near a real send

This agent drafts compliant-*shaped* copy (honest subject lines, no false
urgency, opt-out language, sender-identification placeholders) because
that's good practice regardless. It does **not** make the underlying
campaign legal — that depends on how it's actually sent, which is outside
this agent's scope entirely.

**Email — CAN-SPAM Act.** Cold commercial email to businesses is generally
permitted in the US without prior consent, but requires: accurate
header/from information, a non-deceptive subject line, a valid physical
postal address (why `{{SENDER_PHYSICAL_ADDRESS}}` exists), a working
opt-out mechanism honored within 10 business days, and no continuing to
email someone who opted out. This agent's copy is shaped for these
requirements; it doesn't verify your actual sending infrastructure honors
them.

**SMS — TCPA, meaningfully stricter than email.** The Telephone Consumer
Protection Act generally requires **prior express consent** before sending
marketing texts to a wireless number, particularly when sent via an
autodialer. A phone number scraped from a Google Business listing is not
consent. Small-business "public" numbers are frequently the owner's actual
personal cell, which strengthens rather than weakens the consumer-protection
concern. Unlike the email path, there isn't a clean "this is fine for B2B
outreach" reading here — **get actual legal advice before sending SMS to
any of these numbers**, not just before running this script. The SMS
section of every draft carries this same warning inline.

## Known limitations

- No fact-checking beyond what's passed in — the prompt is instructed not
  to fabricate details, but hasn't been adversarially tested against a
  large lead sample.
- Follow-up day-offsets are chosen by the model per lead, not from a fixed
  schedule — reasonable in the two spot-checks so far, not guaranteed
  consistent across hundreds of leads.
- No dedupe against leads that already have a draft from a different run
  configuration (e.g. `--force` regenerating with a changed prompt) — old
  and new drafts aren't diffed for you.
