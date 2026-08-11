# Website/SEO Audit Agent — Design Spec

**Date:** 2026-08-11
**Status:** Approved for implementation planning
**Related:** [ARCHITECTURE.md](../../../ARCHITECTURE.md) §3, §19 (Discovery agent, site_check.py)

## 1. Purpose

Discovery today decides whether a lead's website is "outdated" using a cheap, single-page heuristic (`agents/discovery/site_check.py`). That heuristic is good enough to *qualify* a lead but produces nothing a human can put in front of a prospect as evidence. This feature adds a real audit step that produces concrete, specific findings — real Core Web Vitals, real on-page SEO gaps, real conversion friction points — so the Outreach and Dossier agents can pitch "here are 5 things costing you customers" instead of a generic "your site looks outdated."

This is a direct extension of an existing, already-built agent (Discovery), not a new department. It stays in the same zero-LLM, deterministic, cost-conscious style as the rest of Discovery.

## 2. Non-goal: this is not the prospect scoring feature

A separate, previously-discussed follow-on feature will compute a weighted 0–100 prospect score from these signals (mirroring the chart's "PROSPECT SCORE: 94/100" format). This spec produces the raw signals that feature would consume. Building the scoring formula is explicitly out of scope here.

## 3. Scope: what gets checked in v1

### Technical (new — requires the PageSpeed Insights / CrUX API call)
- Core Web Vitals: real LCP, CLS, INP (CrUX field data where available; PSI lab data as fallback for sites too small to have CrUX history)
- Overall Lighthouse-style performance score (0–100)
- Mobile-friendliness (from PSI directly, replacing the current crude "has a viewport meta tag" guess)

### On-page SEO (new — parsed from the same HTML fetch `site_check.py` already makes)
- Title tag: present, length in ~50–60 char range
- Meta description: present, length in the ~150–160 char range
- H1: present, exactly one
- Heading hierarchy: no skipped levels (e.g., H1 → H3 with no H2)
- Canonical tag: present and self-referencing
- Robots meta tag: specifically flagging accidental `noindex`
- Structured data: any JSON-LD present, specifically `LocalBusiness`/`Organization`
- `sitemap.xml` and `robots.txt` existence (one `HEAD` request each)

### Conversion basics (new — parsed from the same HTML fetch)
- Phone number visible on the homepage (regex match)
- Contact form or booking link present
- CTA presence (heuristic match on button/link text: "call," "book," "contact," "schedule," etc.)

### Explicitly excluded from v1 (and why)
- **Backlinks, keyword rankings, competitor comparison, topical authority** — require a paid SEO API (Ahrefs/SEMrush/Moz/DataForSEO) or heavy scraping. Real cost and complexity, not justified for a pre-sale pitch tool yet.
- **Deep UX judgment** (navigation quality, trust signals, readability) — not deterministically checkable; would require an LLM call per lead, conflicting with keeping Discovery zero-LLM at bulk volume.
- **Multi-page analysis** (duplicate content across pages, internal link graph) — requires crawling beyond the homepage; a real feature, but a bigger scope jump than extending the existing single-page check.

## 4. Architecture

New module: `agents/discovery/site_audit.py`, sibling to `site_check.py` — not merged into it. `site_check.py` continues to do exactly what it does today (the qualification heuristic deciding outdated vs. modern). `site_audit.py` is a separate, richer enrichment step.

**Trigger condition:** runs only for leads that land in `qualification_status = qualified_outdated`. Not run for `qualified_no_website` (no site exists to audit), not run for `disqualified_modern` (never contacted, auditing would waste PSI quota for no reason). This keeps the new API call scoped tighter than "every lead with a website."

Called from `discovery_agent.py` immediately after `site_check.py`, in the same per-lead pass, same as today's flow.

## 5. Data model changes

New columns on the existing `leads` table in `agents/discovery/schema.sql` (matching the existing pattern where `website_signals` already lives directly on `leads` rather than a child table):

```sql
ALTER TABLE leads ADD COLUMN audit_status TEXT DEFAULT 'not_run';  -- not_run | ok | error | skipped
ALTER TABLE leads ADD COLUMN audit_score INTEGER;                   -- PSI performance score, 0-100
ALTER TABLE leads ADD COLUMN audit_signals TEXT;                    -- JSON blob: CWV values, on-page SEO findings, conversion flags
ALTER TABLE leads ADD COLUMN audit_run_at TEXT;
```

Dossier already reads `leads.db`, so these fields become available to it automatically once the schema changes land. Dossier's system prompt needs a small update to actually reference `audit_signals` when generating pitch talking points — a prompt change, not a new agent capability.

## 6. Configuration

- One new `.env` var: `PSI_API_KEY` (Google Cloud API key with PageSpeed Insights API enabled — same GCP project as Places, one more API to enable in Cloud Console)
- No new Python dependency. PSI is a plain JSON `GET` to `https://www.googleapis.com/pagespeedonline/v5/runPagespeed`; `httpx` (already a dependency) handles it.

## 7. Error handling

Same pattern as `site_check.py`: any PSI failure (429 rate limit, timeout, malformed URL, non-200 response) sets `audit_status = 'error'` and moves on — never blocks or crashes the batch. Reuse the exponential-backoff retry logic already implemented in `agents/discovery/places_client.py` rather than writing a second implementation of the same pattern.

## 8. Cost

PageSpeed Insights and CrUX are both free APIs (quota-limited, not billed). At pilot volume (tens to low hundreds of `qualified_outdated` leads per run), this adds $0 in API spend — not just "cheap," genuinely free within default quota.

## 9. Testing

Following the project's existing verification pattern (see ARCHITECTURE.md — every agent so far was "verified by reading actual output, not just trusting exit codes"):

1. `--dry-run` mode: sanity-checks the code path with fake data, no real PSI calls
2. Real smoke test against a handful of actual `qualified_outdated` leads from the existing pilot batch
3. Manually spot-check the computed `audit_signals` against the real site (open the site, confirm the title tag, phone visibility, CWV numbers reported actually match reality) — not just confirm the script exits 0

## 10. Follow-on work (not in this spec)

- Prospect scoring: weighted 0–100 score computed from `audit_signals` (separate spec)
- Feeding `audit_signals` into Dossier's prompt (small, mechanical follow-up once this lands)
