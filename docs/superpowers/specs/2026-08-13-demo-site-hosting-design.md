# Demo Site Hosting — Design Spec

**Date:** 2026-08-13
**Status:** Approved for implementation planning
**Related:** [ARCHITECTURE.md](../../../ARCHITECTURE.md) §3, §6, §16 (roadmap item #2), §19 (Website Demo Generation agent)

## 1. Purpose

`agents/website_demo` already builds a full, on-page-SEO-ready concept site per qualified lead, but the output only ever exists as local files in `output/<slug>/`. Outreach copy has nothing real to link to; the dossier can only describe a demo in words ("a concept demo has been built (not yet hosted/live)"). This closes ARCHITECTURE.md §16 roadmap item #2 by giving each demo a real, working URL.

The hosting mechanism itself (`--site-base-url`, canonical/`og:url`/`sitemap.xml` generation) was already built in an earlier session specifically anticipating this — see `agents/website_demo/README.md`'s "On-page SEO" section. This spec is about the missing half: an actual place to upload to, and a deploy step.

## 2. A pre-existing bug this spec also fixes

`generate_demo.py`'s `write_seo_files()` currently writes a `robots.txt` inside each `output/<slug>/` folder. Once hosted at `{base_url}/{slug}/`, that file has no effect — compliant crawlers only ever check `robots.txt` at a site's root (`{base_url}/robots.txt`), never inside a subdirectory. This has been silently non-functional since it was written; nothing has been hosted yet to expose it. This spec removes the broken per-slug file and replaces it with a real root-level one (§5).

## 3. Requirement: noindex by default

These are unsolicited concept mockups built for businesses that haven't agreed to anything — sent cold, before any relationship exists. Decision (confirmed with the user): every demo is **not indexable by search engines by default**. A shop's real customers should never be able to find a mockup the shop didn't make or ask for via Google, and near-duplicate template content across many leads is exactly the kind of thing worth avoiding proactively (see ARCHITECTURE.md §13's existing no-fabrication/no-scraping ethics section — this is the same spirit).

A lead is only made indexable once they've actually responded (the point where `reply_triage` would classify their reply) — a deliberate human action, not automatic.

Two layers are used together, because they serve different purposes:

1. **`<meta name="robots" content="noindex">`** in every page's `<head>`, unless the lead's slug is explicitly cleared. This is what actually keeps a page out of search results, including if someone links to it directly — `robots.txt` alone can still let a bare URL appear in search results without content if it's discovered via an external link.
2. **A real root `robots.txt`**, generated at deploy time, blocking crawling of everything except explicitly-cleared slugs. Belt-and-suspenders with (1), and the piece that was broken (§2).

## 4. Hosting choice: Cloudflare Pages

Evaluated against Netlify and S3+CloudFront (the three candidates named in ARCHITECTURE.md §16):

| | Cloudflare Pages (chosen) | Netlify | S3 + CloudFront |
|---|---|---|---|
| Setup | Free account, one API token | Free account, one token | AWS account, bucket + distribution + invalidation |
| Free tier | Unlimited bandwidth/requests | Generous, some bandwidth cap | Real (tiny) per-request/storage cost |
| Per-path custom headers | `_headers` file — not needed here, see §3 | `_headers` file | Needs Lambda@Edge/CloudFront Functions |
| Fit | Best match for current scale (10 leads, 898KB total) and "minimal setup" preference | Equally valid, no reason to prefer over Cloudflare here | Meaningfully more setup for no current benefit; revisit only if this outgrows a free-tier static host |

No custom domain yet — demos live at `https://<project-name>.pages.dev/<slug>/` using Cloudflare's free subdomain. A real domain can be added later without touching the folder structure, since the URL scheme (`{base_url}/{slug}/...`) was already built to be base-URL-agnostic.

**Deploy mechanism:** Cloudflare's own `wrangler` CLI (Node.js-based), invoked via `npx wrangler pages deploy` from `deploy.py`'s subprocess call. This is the one piece of this project that isn't pure Python — every other agent is a plain `venv` with no external toolchain. The alternative (hand-rolling Cloudflare's direct-upload REST protocol in `httpx`, which requires hashing every file, uploading a manifest, then uploading only the missing files in batches) was rejected as meaningfully more custom code to build and maintain for 10 small HTML folders, with no real benefit over calling Cloudflare's own well-tested CLI. Confirmed with the user that Node/npm (v24.19.0 / 11.17.0) are already installed, so this costs nothing extra to adopt.

## 5. Architecture

All changes live inside the existing `agents/website_demo/` agent — no new agent, no new venv.

**`generate_demo.py` changes:**
- New `ROBOTS_META_TAG` token, computed in `page_tokens()` alongside the existing `CANONICAL_TAG`/`OG_URL_TAG`: renders `<meta name="robots" content="noindex">` unless the lead's slug is in `indexable_slugs.txt`, in which case it renders nothing (same "omit rather than assert" pattern already used when `site_base_url` is unset).
- `write_seo_files()` no longer writes a per-slug `robots.txt` (§2). `sitemap.xml` generation is unaffected — a sitemap, unlike `robots.txt`, does not need to live at the site root, so the existing per-slug sitemap is already correct as built.
- New small helper to read `indexable_slugs.txt` (one slug per line; missing file or blank lines tolerated, treated as "nothing indexable yet").

**`template/*.html` changes:** all 10 files in `HTML_FILES` get one new `{{ROBOTS_META_TAG}}` placeholder in `<head>`, next to the existing `{{CANONICAL_TAG}}` line.

**New `indexable_slugs.txt`:** plain text, one slug per line, human-edited directly (`echo <slug> >> indexable_slugs.txt`). No database, no CLI subcommand — this changes rarely and deliberately, matching the project's existing preference for the smallest state mechanism that does the job. Contains real business slugs, so like every `.db` file it's operational state, not source — added to `.gitignore` (§8), not committed.

**New `deploy.py`:**
1. Read `indexable_slugs.txt`.
2. Validate preconditions (§6) — fail fast with a clear message before ever invoking `wrangler`.
3. Write `output/robots.txt` (the real root file):
   ```
   User-agent: *
   Disallow: /
   Allow: /<indexable-slug-1>/
   Allow: /<indexable-slug-2>/
   ```
   (Zero indexable slugs → just `Disallow: /`, which is also the correct starting state before any lead has ever replied.)
4. Run `npx wrangler pages deploy output --project-name=<CLOUDFLARE_PROJECT_NAME>` via subprocess, streaming wrangler's own stdout/stderr live rather than capturing and summarizing it.
5. On success, print the live base URL (`https://<project-name>.pages.dev`) and a reminder that it reflects whatever was last generated — re-run `generate_demo.py --force` first if any demo content changed.

**`.env` additions:** `CLOUDFLARE_PROJECT_NAME`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` (the latter two are read directly by `wrangler` itself via standard Cloudflare env-var conventions, not parsed by `deploy.py`). `DEMO_SITE_BASE_URL` already exists and should be set to `https://<project-name>.pages.dev` — chosen and known before the first deploy, since the project name is picked by the human up front rather than assigned afterward, avoiding a "deploy once just to discover the URL" step.

**`README.md`:** documents the deploy step, the `CLOUDFLARE_*` env vars, `indexable_slugs.txt`'s format and purpose, and the noindex-by-default behavior.

## 6. Workflow

**Initial setup (human, one time):** create a free Cloudflare account, create a Pages project with a chosen name, create an API token, set the three `CLOUDFLARE_*` env vars and `DEMO_SITE_BASE_URL` in `.env`.

**Normal generate → deploy flow:**
1. `python generate_demo.py` (as today) — every demo now also gets a noindex meta tag by default.
2. Review as already happens (locally, or via the approval queue for the associated outreach draft).
3. `python deploy.py` — writes the real root `robots.txt`, uploads `output/`, prints the live URL.

**When a lead responds and should become findable (human-driven, same "human acts the moment they see something real" pattern as `reply_triage`):**
1. Add their slug to `indexable_slugs.txt`.
2. `python generate_demo.py --force` — regenerates every existing demo (cheap: zero LLM calls, pure template substitution, well under 1MB total); only the newly-cleared lead's noindex tag actually changes.
3. `python deploy.py` — rebuilds `robots.txt` from the updated file and redeploys.

No new CLI flag needed on `generate_demo.py` — `--force` already exists and already regenerates the full batch.

## 7. Error handling

- Missing `indexable_slugs.txt` → treated as empty (nothing indexable), not an error.
- Missing `CLOUDFLARE_PROJECT_NAME` / `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` → `deploy.py` fails fast with a message pointing at the README setup section, before ever shelling out to `wrangler`.
- Empty `output/` (nothing generated yet) → `deploy.py` refuses to deploy rather than pushing an empty site.
- `wrangler` failure (bad token, network error, `npx` unable to resolve the package) → its own stderr is streamed through directly, not swallowed or retried; a deploy failure should be loud, unlike the transient-API-retry cases elsewhere in this project (Places/PSI), since this isn't a high-volume automated call worth smoothing over.

## 8. Configuration / repo changes

- Add `agents/website_demo/indexable_slugs.txt` to `.gitignore`, alongside the existing `*.db` pattern — it's operational state (real business slugs), not source, matching the comment already there ("Local databases (operational state, not source)").
- No new Python dependency (`deploy.py` uses only `subprocess` and the standard library beyond what `generate_demo.py` already imports).

## 9. Testing

Following this project's established pattern (verify pure logic with real automated tests; verify real external calls by actually exercising them, not mocking):

1. New `test_generate_demo.py` (this agent's first test file — matches ARCHITECTURE.md §8's "worth doing incrementally" note): the `indexable_slugs.txt` parser (missing file / empty file / populated file, blank-line tolerance) and the `ROBOTS_META_TAG` computation for both indexable and non-indexable slugs — pure functions, zero network, zero cost.
2. `deploy.py`'s `robots.txt`-building logic gets the same treatment: correct `Disallow`/`Allow` output for zero, one, and multiple indexable slugs.
3. The actual `wrangler pages deploy` call is not unit-tested (real external service call, not meaningfully mockable without just testing the mock). Verified instead by an actual deploy against the user's real free Cloudflare account, then confirming live in a browser that: a cleared demo is reachable and reads correctly, a non-cleared demo's page source actually contains the noindex meta tag, and `https://<project-name>.pages.dev/robots.txt` reflects the current `indexable_slugs.txt` correctly.

## 10. Follow-on work (not in this spec)

- Wiring the real live demo URL into Outreach's drafts and Dossier's talking points once hosting exists — currently neither agent references a demo URL at all, only "a concept demo has been built (not yet hosted/live)". Small and mechanical once this lands, same shape as the `audit_signals` → Dossier follow-up that was done previously.
- A real custom domain, once wanted, in place of the free `.pages.dev` subdomain.
- Wiring `deploy.py` into `run_pipeline.py` as an opt-in stage (explicitly deferred — deploy trigger was chosen to stay a deliberate manual command for now, matching this project's human-in-the-loop pattern; §6 of ARCHITECTURE.md's orchestrator section already treats `--run-discovery`/`--run-dossier` the same way).
