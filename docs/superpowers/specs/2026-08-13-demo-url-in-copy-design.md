# Real Demo URL in Outreach & Dossier Copy — Design Spec

**Date:** 2026-08-13
**Status:** Approved for implementation planning
**Related:** [ARCHITECTURE.md](../../../ARCHITECTURE.md) §3, §19 (Outreach Copywriting, Sales Handoff Dossier); follow-on item from [2026-08-13-demo-site-hosting-design.md](2026-08-13-demo-site-hosting-design.md) §10

## 1. Purpose

Demo site hosting now exists (`agents/website_demo/deploy.py`), but nothing downstream references the real URL. `agents/outreach/generate_drafts.py`'s system prompt already tells Claude to invite the lead to "take a look" at a concept site, but the script never tells Claude whether a demo exists at all, let alone where — so it currently writes vague copy with nothing to actually look at. `agents/dossier/generate_dossier.py` tracks a `demo_exists` bool and correctly refuses to overclaim ("not yet hosted/live"), but that claim is now stale for every lead whose demo actually is hosted.

This closes that gap in both agents with the same mechanism.

## 2. Scope

In scope: computing a real, live demo URL per lead in both agents, and using it in generated copy/rendered output. Out of scope, deliberately: any change to `website_demo`, `deploy.py`, or the hosting mechanism itself — those are done and unaffected.

## 3. The URL-presence rule

A lead's demo URL is only ever real when **both** are true:
1. A local demo folder exists for that lead (`output/<slug>/`)
2. `DEMO_SITE_BASE_URL` is configured in the agent's own `.env`

Folder-exists-alone is not enough — the folder could exist locally without ever having been deployed (`generate_demo.py` was run but `deploy.py` never was, or not since). This mirrors the exact gating `website_demo/generate_demo.py` already uses for its own SEO tags (canonical/`og:url`/`sitemap.xml` — all gated on `site_base_url` being set, not just demo generation having happened).

This is a known, accepted limitation, not solved here: there is no single source of truth confirming a demo folder's *current* content actually matches what's live on Cloudflare Pages (e.g., a demo regenerated locally but not yet redeployed). This matches the project's existing risk tolerance for exactly this class of staleness — see `agents/website_demo/README.md`'s "Before this goes anywhere near a lead" section, which already documents the same class of gap for demo-existence tracking generally, and puts the burden on human review before anything is sent, which remains true here.

## 4. URL construction

Both agents independently build the URL using the identical scheme `website_demo/generate_demo.py`'s `page_url()` already uses for `index.html`: `f"{base_url.rstrip('/')}/{slug}/"`. Each agent already has (or will gain) its own `slugify()` — the project's existing pattern is per-agent duplication of small helpers like this rather than a shared import across agent boundaries (see ARCHITECTURE.md §15: "Each agent is self-contained... rather than sharing a monorepo-style dependency tree — deliberate, so agents can be developed, tested, and eventually deployed independently"). This spec follows that same pattern rather than introducing a cross-agent dependency.

## 5. `agents/outreach/generate_drafts.py` changes

**New:**
- `DEFAULT_DEMO_DIR = Path(__file__).parent.parent / "website_demo" / "output"` constant, and a `--demo-dir` CLI arg (mirrors the existing `--db`/`--suppression-db`/`--output-dir` pattern in this same file)
- `demo_url_for(business_name: str, city: str, demo_dir: Path, site_base_url: str | None) -> str | None`: slugifies the lead, checks `(demo_dir / slug).exists()`, returns the constructed URL only if that folder exists **and** `site_base_url` is set, else `None`
- `site_base_url` read from `os.environ.get("DEMO_SITE_BASE_URL", "")` in `main()`, same `.strip() or None` pattern `website_demo/generate_demo.py` already uses for the same env var

**Changed:**
- `build_user_prompt(lead, demo_url)`: adds a `Demo status:` line with three states:
  - No demo folder: `"No concept demo has been built for this shop yet."`
  - Demo folder exists, no live URL: `"A concept demo has been built for this shop but isn't hosted/live yet -- do not include a link."`
  - Live URL: `"A concept demo is live for this shop at {demo_url} -- reference this exact URL in the email (and follow-ups) when inviting them to look."`
- `SYSTEM_PROMPT`: add explicit instructions --
  - When a live URL is given, use it verbatim in the email body's call-to-action (e.g., "take a look here: {url}") and in both follow-up emails -- never alter, shorten, or re-type the URL differently than given.
  - Never fabricate or imply a URL when none is given, or when the demo exists but isn't hosted -- the existing "don't overclaim" instruction already covers not claiming the site is live; this extends it to not claiming there's a link when there isn't one.
  - **The SMS body must never include the demo link, regardless of whether one exists** -- keep the existing SMS pitch style (mentions the concept, invites a reply) link-free. (Decision confirmed with the user: SMS's 320-character budget including the mandatory opt-out line, plus a bare link in a cold text reading more like spam/phishing than a cold email does.)
- `generate_draft(client, lead, demo_url)`: threads `demo_url` into `build_user_prompt()`
- `main()`: computes `demo_url` per lead via `demo_url_for()` before calling `generate_draft()`, passes it through

**Unchanged:** `OUTPUT_SCHEMA`, `render_markdown()`, suppression-checking logic, follow-up scheduling logic -- none of this needs to know about the URL, it only flows through the prompt into Claude's generated `email_body`/`followups` text, same as today's phone/city/state facts.

## 6. `agents/dossier/generate_dossier.py` changes

**New:**
- `demo_url_for(business_name: str, city: str, demo_dir: Path, site_base_url: str | None) -> str | None` -- same function, duplicated per §4's reasoning (dossier already has its own `slugify()`, distinct from outreach's and website_demo's)
- `site_base_url` read from `DEMO_SITE_BASE_URL` in `main()`, same pattern as above

**Changed:**
- `build_user_prompt(lead, demo_exists, draft_exists, funnel)` → the `demo_exists: bool` parameter becomes `demo_url: str | None`. The `Demo site status:` line gains a third state:
  - `None` + folder doesn't exist: `"no demo built yet"` (unchanged wording)
  - `None` + folder exists: `"a concept demo has been built (not yet hosted/live)"` (unchanged wording)
  - Real URL: `f"a concept demo is live at {demo_url}"`
- `query_claude(...)` and `main()`: thread `demo_url` through instead of the old `demo_exists is not None` bool
- `render_markdown(lead, dossier, demo_path, draft_path, demo_url)`: the "## Website Demo" section shows the real clickable link when `demo_url` is set (e.g., `f"Live demo: {demo_url}"` as a markdown link) instead of the current `f"Demo exists locally at `{demo_path}`."` line when a URL is available; falls back to existing text (local path or "no demo yet") when it isn't.
- `SYSTEM_PROMPT`: minor addition -- when a live URL is present, the dossier's `research_summary`/`talking_points` may reference that the demo is live and shareable (a real, useful fact for a salesperson to know), same "don't fabricate" discipline as the rest of the prompt already enforces.

**Unchanged:** `DOSSIER_SCHEMA`, funnel-context logic, web_search tool config, everything else.

## 7. Configuration

- `DEMO_SITE_BASE_URL=` added to `agents/outreach/.env.example` and `agents/dossier/.env.example`, matching the comment style already in `agents/website_demo/.env.example`. Each agent's own `.env` needs the value set manually -- no shared config file, consistent with every other duplicated var across this project's agents (e.g. `ANTHROPIC_API_KEY` already appears independently in `outreach/.env`, `dossier/.env`, and `reply_triage/.env`).
- No new Python dependency in either agent.

## 8. Error handling

No new failure modes. `demo_url_for()` never raises -- a missing folder or unset env var simply yields `None`, which both agents already have a defined, correct behavior for (today's existing "no demo yet" / "not hosted" states). This matches the graceful-degradation pattern used everywhere else in this project (e.g. `website_demo/generate_demo.py` already treats a missing `site_base_url` as "omit the SEO tags," not an error).

## 9. Testing

Both `agents/outreach` and `agents/dossier` currently have zero automated tests (ARCHITECTURE.md §8 explicitly flags this as "worth doing incrementally," the same framing under which `website_demo` got its first tests in the hosting work). `demo_url_for()` is a small pure function in each file (no network, no LLM call) -- worth a first test file per agent:

- `agents/outreach/test_generate_drafts.py` (new): folder doesn't exist → `None`; folder exists, no base URL → `None`; folder exists and base URL set → correct URL string; base URL with/without a trailing slash both produce the same correctly-formed URL.
- `agents/dossier/test_generate_dossier.py` (new): same four cases, against dossier's own copy of the function.

`build_user_prompt()`'s three-state `Demo status:`/`Demo site status:` line-selection logic in both agents is also pure and cheap to test directly (given a fixed `demo_url` value, assert the right sentence appears) -- include alongside the `demo_url_for()` tests.

Not tested (consistent with how the rest of both agents are verified today, per ARCHITECTURE.md §8's existing "manual verification" convention for anything requiring a live Claude call): the actual generated email/SMS/dossier copy quality, i.e. whether Claude actually uses the URL naturally and never in the SMS. That's verified by generating one real draft/dossier for a lead with a live demo URL (once one exists post-merge -- see §10) and reading the actual output, matching how every other prompt change in this project has been verified.

## 10. Follow-on / prerequisites

This spec assumes at least one lead has a real, live demo URL to test against once implemented. As of the demo-hosting branch's merge, `indexable_slugs.txt` is empty and no lead has been marked as responded -- but that's irrelevant here: `demo_url_for()`'s URL construction doesn't depend on `indexable_slugs.txt` or search-engine indexability at all, only on the demo folder existing and `DEMO_SITE_BASE_URL` being set. Verification can use any already-hosted (`noindex`) demo lead; indexability and outreach-copy-linking are unrelated concerns.
