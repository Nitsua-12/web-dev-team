# Discovery Agent (MVP)

Finds tattoo shops via the Google Places API, flags each one as a lead if it
has no website or an outdated one, and writes structured records to a local
SQLite database. First agent in the outreach pipeline -- everything
downstream (research, website demo generation, outreach copy, sales
handoff) reads from the `leads` table this produces.

`places_client.py` also exposes `get_place_details()` (single-place GET,
not the batch text search) -- added for and used by
[../reverify](../reverify), which reuses this file directly rather than
duplicating a second Places API client.

## Setup

1. Create a virtualenv and install deps:
   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and add your Google Places API key
   (needs the Places API (New) enabled on the project).
3. Confirm current pricing before running a real batch:
   https://developers.google.com/maps/documentation/places/web-service/usage-and-billing
   -- the fields this agent requests (website, phone) bill at Google's
   higher "Enterprise" SKU tier, not the base tier.

## Running

```
# Sanity-check the pipeline with fake data, no API calls, no cost
python discovery_agent.py --dry-run

# Real run, but only the first 3 seed cities (cheap smoke test)
python discovery_agent.py --limit-cities 3

# Real run, one state only
python discovery_agent.py --state TX

# Full seed batch (25 major metros, ~20 states)
python discovery_agent.py
```

Output goes to `leads.db` (SQLite) by default; override with `--db path.db`.
Re-running is safe and resumable: `search_cells` tracks which city/state
queries already ran, and `leads` dedupes on `google_place_id`, so a
partial or interrupted run just picks up where it left off.

## How qualification works

For each place returned by Places Text Search:

- **No `websiteUri` field** -> `qualified_no_website`. Cheapest, most
  reliable signal -- no extra fetch needed.
- **Has a website** -> fetched once (respecting `robots.txt`) and scored
  by `site_check.py` on cheap heuristics: no HTTPS, missing viewport meta
  tag (not mobile-responsive), stale copyright year, generic
  page-builder splash markers, legacy tech markers (`<marquee>`,
  Flash `<object>` embeds, "best viewed in Internet Explorer"). Score
  >= 2 -> `qualified_outdated`, otherwise -> `disqualified_modern`.
- **Fetch blocked by robots.txt or failed** -> `needs_review` (don't
  guess; a human or a later pass should look at these).

## Website audit (qualified_outdated leads only)

For every lead that qualifies as `qualified_outdated`, a second pass
(`site_audit.py`) runs a real audit: PageSpeed Insights performance score
and Core Web Vitals (LCP, CLS, INP field data where available), plus
deterministic on-page SEO checks (title/meta description length, H1
count, heading hierarchy, canonical tag, `noindex` detection, structured
data, sitemap/robots.txt existence) and conversion checks (phone number,
contact form/booking link, CTA presence). Results land in the `leads`
table's `audit_status`, `audit_score`, `audit_signals`, and
`audit_run_at` columns.

This does **not** run for `qualified_no_website` (nothing to audit) or
`disqualified_modern` (never contacted) leads.

Requires `PSI_API_KEY` in `.env` -- enable the PageSpeed Insights API on
the same Google Cloud project used for Places, then create/reuse an API
key. PageSpeed Insights and CrUX are both free, quota-limited APIs, not
billed.

Never runs during `--dry-run` (the PSI call is explicitly skipped
regardless of the fake data's qualification status).

## Scaling beyond the pilot batch

`cities_seed.py` currently has ~25 major metros. This was a deliberate
choice, not a limitation of the pipeline: running all of Google Places
API across every US city/zip in one shot costs roughly $1,200-1,500 (see
project notes) before you've confirmed the qualification heuristic
actually finds sellable leads. To scale up:

1. Validate lead quality on this batch first (spot-check a sample of
   `qualified_outdated` and `qualified_no_website` rows).
2. Add more rows to `SEED_CITIES` -- ideally sourced from a full US
   Census Places dataset rather than hand-typed, in batches (e.g.
   state-by-state) so cost and quality can be checked incrementally.
3. No code changes needed for either step -- the pipeline scales with
   the seed list.

## Known gaps (by design, for later agents/iterations)

- No LLM calls in this agent -- it's pure API + heuristics, kept cheap
  and fast since it may process tens of thousands of businesses.
- Doesn't yet write anywhere but local SQLite -- swapping in Postgres
  later means changing `db.py` only, the rest of the pipeline is
  storage-agnostic.
- Doesn't dedupe near-duplicate businesses across overlapping city
  search radii beyond exact `google_place_id` match (a shop right on a
  metro boundary could theoretically appear under two labels but will
  still only get one row).
