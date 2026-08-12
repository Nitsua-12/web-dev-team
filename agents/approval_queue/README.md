# Approval Queue

The literal review-and-approval step your original brief required. Before
this, "review" meant opening a markdown file by hand and there was no
record of whether anyone had actually looked at it. This is a real local
web UI: open it, read the full draft, click Approve or Reject.

No pip dependencies — Python's built-in `http.server`, matching every
other stdlib-only agent in this project. **Binds to `127.0.0.1` only** —
this is a local, single-user tool and is never reachable from the
network.

## Running

```
python server.py
```

Opens `http://127.0.0.1:8420` in your browser automatically. Leave the
terminal running while you use it; `Ctrl+C` to stop.

## What it does

- **Pending tab** — every lead with a draft that hasn't been decided on
  yet. Automatically excludes anything already suppressed or already
  marked sent (both flagged with a badge if you land on them another
  way) — no reason to review something that's already been acted on.
- **Click a lead** — full detail view: subject, complete email body,
  SMS, both follow-ups with their day offsets. Also shows whether a
  demo site and dossier exist yet for this lead, and that lead's current
  `qualification_status` in the meta line (city/state/phone/status) — see
  Known Limitations for what this does and doesn't protect you from.
- **Approve / Reject**, with an optional notes field (e.g. "tone's too
  generic, needs a rewrite"). The decision and note persist.
- **Approved / Rejected tabs** — see what's already been decided, with
  the note attached. **Reset to pending** on either undoes a decision if
  you change your mind.

## What "approved" actually means right now

Approval doesn't send anything — nothing in this pipeline can send
anything yet. What it does is give you a real, queryable record of what
you've cleared to go out, the moment sending does exist. That's the
right scope for this tool today: the decision infrastructure, ready
before the thing it gates is built, not after.

## Verified live in a browser, not just by reading the code

- All 10 real leads with drafts correctly appeared in Pending, with
  accurate subject-line previews.
- Opened a full detail view (Village Tattoo NYC) — confirmed the entire
  email body, SMS, and both follow-ups rendered correctly, matching the
  actual `draft.json` content.
- Approved it, watched it disappear from Pending and correctly appear
  (alone) in the Approved tab.
- Rejected a second lead (Addiction NYC) with a note, confirmed the note
  persisted and displayed correctly in both the row detail and the
  textarea on return.
- Used **Reset to pending** on both, confirmed they returned to Pending,
  and confirmed `approvals.db` was genuinely empty afterward — no test
  data left behind.

## Known limitations

- **The Pending list doesn't surface a status change at all; the detail
  view shows it but doesn't flag it.** A lead [reverify](../reverify)
  has since moved to `needs_review` or `disqualified_modern` still shows
  up in Pending looking exactly like any other lead — the list view
  (`get_pending_leads` in `server.py`) doesn't even fetch
  `qualification_status`. Click into the detail view and it's there in
  plain text in the meta line, same visual weight as the phone number —
  nothing highlights it as changed or warns that it no longer matches
  what the draft below it assumes. A human has to already know to look
  and recognize `needs_review` as a red flag. Real example from this
  project: Village Tattoo NYC's draft still says `qualified_outdated` in
  its own header while the lead's actual current status is
  `needs_review` — see
  [../reverify/README.md](../reverify/README.md#known-limitations) and
  [../outreach/README.md](../outreach/README.md#a-draft-can-go-stale-after-its-generated)
  for the full story. Worth fixing here specifically, since this is the
  exact screen meant to catch this before something gets approved.
- **Single-writer, no auth.** Fine for a local single-user tool; would
  need real access control before ever being anything else.
- **No connection to the scheduler yet.** Approving a lead's initial
  draft doesn't automatically feed into
  [scheduler](../scheduler)'s `mark-sent` — those stay two separate
  manual steps for now (approve here, then record the actual send there
  once you've sent it).
- **No bulk actions.** Every decision is one lead at a time by design —
  intentional friction for something that's supposed to be reviewed,
  not rubber-stamped, but worth reconsidering if the queue ever gets
  large.
- **Port 8420 is hardcoded.** Change `PORT` in `server.py` if it
  conflicts with something else on your machine.
