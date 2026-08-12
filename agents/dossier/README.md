# Sales Handoff Dossier Agent

The "Human Sales Step" from the original project brief — the point where
the AI system stops and a person takes over. This agent doesn't contact
leads or make decisions; it assembles the context a salesperson needs the
moment a lead expresses interest: lead history, a research summary,
website demo status, communication history, recommended talking points,
an estimated budget, and a likelihood-of-closing assessment.

## Running

```
python generate_dossier.py --business "Village Tattoo NYC"  # recommended: one lead at a time
python generate_dossier.py --limit 3        # smoke test on the first 3
python generate_dossier.py                  # every qualified lead -- costs add up, use deliberately
python generate_dossier.py --force          # regenerate existing dossiers
```

**Use `--business` for everyday use, not a full batch run.** This is the
most expensive call in the pipeline (real tokens plus a `web_search` call
per lead), and there's rarely a reason to generate one for every
qualified lead when only a few are ever about to actually be contacted.
`run_pipeline.py` reflects this too — Dossier is opt-in there
(`--run-dossier`), not part of the default run, for the same reason.

Pulls from `../discovery/leads.db`, checks whether a demo exists in
`../website_demo/output/<slug>/`, and whether a draft exists in
`../outreach/drafts/<slug>/draft.md`. Output lands in
`dossiers/<slug>/dossier.md`. Re-running is safe — existing dossiers are
skipped unless you pass `--force`.

Uses `claude-sonnet-5` with the web_search tool (server-side, no scraping —
same ToS-compliant approach used elsewhere in this project) plus structured
outputs, so research findings feed into a guaranteed-valid JSON draft
before rendering to markdown.

## What's in a dossier

- **Lead history** — straight from Discovery's data: name, address, phone,
  when/how it was found, why it qualified.
- **Research summary** — whatever Claude's web search turns up (review
  counts, social presence, anything notable). If nothing useful comes up,
  it says so rather than padding with generic filler — confirmed in
  testing, not just prompted for.
- **Website demo / communication history** — just status flags (does a
  demo exist, does a draft exist, has anything been sent) pulled from the
  other two agents' output directories. Not fabricated — if those agents
  haven't run for a lead yet, the dossier says so plainly.
- **Talking points** — 3-5 concrete points grounded in the lead's actual
  data and research findings, not generic sales boilerplate.
- **Budget estimate and likelihood of closing** — deliberately **not**
  fake-precise numbers. The model gives a qualitative range/level
  (low/medium/high for likelihood; a rough dollar range for budget) with
  its actual reasoning spelled out, and is instructed to say when its
  confidence is low rather than pick an arbitrary answer. Treat these as
  a starting point for a salesperson's own judgment, not a prediction.

## A dossier can go stale after it's generated

Same gap as outreach's drafts, and for the same underlying reason:
`generate_dossier.py` only ever runs for `qualified_no_website`/
`qualified_outdated` leads (`QUALIFYING_STATUSES` in the code), so it
won't generate a *new* dossier for one [reverify](../reverify) has since
moved to `needs_review` or `disqualified_modern` -- confirmed directly,
not assumed: `generate_dossier.py --business "..." --force` against a
lead in that state refuses outright with "no longer qualified," before
spending a single token.

What it won't do is reach back and fix an **existing** dossier. And
unlike the demo (whose content stays neutral), a dossier is exactly like
a draft here -- it makes real claims that go stale: the `Qualification`
line in Lead History, and Talking Points built directly around the
qualification reason (e.g. "frame the outdated site as a missed
opportunity"). Once the underlying fact changes, those sections are
actively wrong, not just outdated.

Same manual-flag practice as the draft: a clearly marked section
inserted right after the "for internal use" line, explaining what
changed. See `dossiers/village-tattoo-nyc-new-york/dossier.md` for a
real example -- that lead's site started returning a bot-block to the
automated checker, turned out on manual inspection to be a real,
currently-live, HTTPS site (not the outdated one the dossier's talking
points were built around), and got two stacked flags: one from reverify
catching the status change, one from the manual browser check that
found what was actually going on. See
[../outreach/README.md](../outreach/README.md#a-draft-can-go-stale-after-its-generated)
and [../reverify/README.md](../reverify/README.md#known-limitations) for
the same story from the other sides.

## Cost note

Same model as the outreach agent (`claude-sonnet-5`, intro pricing through
2026-08-31) plus web search usage, which is billed per search in addition
to token cost. More expensive per-lead than the copywriting agent because
of the search calls — check current web search pricing before running this
against a large batch.

## Known limitations

- Web search quality varies by how much of a public footprint the shop
  actually has — a shop with no online presence will get a thin research
  summary, which is correct behavior, not a bug, but worth knowing before
  reading too much into an empty section.
- Budget/likelihood estimates are exactly as good as the signals available
  (review counts, social presence, qualification reason) — there's no
  actual financial data or prior sales history feeding into them, because
  none exists yet for a system this new.
- No dossier update mechanism — if the outreach or demo agents run again
  after a dossier was generated (e.g. a draft gets sent, a demo gets
  rebuilt), the dossier doesn't know and needs `--force` regeneration to
  reflect it. Related but distinct from "A dossier can go stale after
  it's generated" above — this one's about *other agents* producing new
  output the dossier hasn't seen; that one's about *the lead itself*
  changing status.
