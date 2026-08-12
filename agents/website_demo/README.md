# Website Demo Generation Agent

Takes qualified leads out of the Discovery Agent's `leads.db` and produces a
personalized demo site for each one -- this is the "here's a modern website
we built for you" artifact the outreach message points to.

## The template

`template/` is an **original design built for this project**, not modeled
on any real business's site. It uses no photography at all -- typography,
color, and a simple SVG line motif do the visual work. That sidesteps the
photo-sourcing problem entirely: nothing here is ever a real business's
actual image, whether theirs or a competitor's.

(Earlier iteration note: this used to default to a real business's actual
site as the template. That was wrong and got fixed -- see git history /
prior conversation. The real site now lives at
`F:\ClaudeProjects\rooster-ink`, untouched and unrelated to this tool.)

## Running

```
python generate_demo.py                  # every qualified lead
python generate_demo.py --limit 3         # smoke test on the first 3
python generate_demo.py --force           # regenerate demos that already exist
python generate_demo.py --no-palette      # skip live photo/color lookup entirely
```

Reads from `../discovery/leads.db` by default. Output lands in
`output/<slug>/`. Re-running is safe: existing demos are skipped unless you
pass `--force`.

## What gets personalized

Business name, street address, city/state, phone number, page
titles/meta descriptions, JSON-LD structured data -- all pulled directly
from Discovery's data via `{{TOKEN}}` placeholders in the template
(`generate_demo.py`'s `build_tokens()` / `apply_tokens()`). This replaced
an earlier version that did fragile literal-string matching against a
specific template's hardcoded content -- that broke in subtle ways (a
leftover state code, a name that only got half-replaced) that only turned
up by actually reading the generated output, not by the script running
without errors. Explicit tokens don't have that failure mode.

## On-page SEO

Every generated page ships with: a real `<title>`/meta description,
`robots` meta, Open Graph + Twitter Card tags, and (on `index.html`) a
`LocalBusiness` JSON-LD block (name, phone, full postal address including
zip, `additionalType: TattooParlor`). All of it comes straight from
Discovery's real data for that lead -- nothing here is fabricated (no
invented `openingHours`, `priceRange`, or `image`, since Discovery
doesn't collect those fields; see `places_client.py`'s field mask if that
ever changes).

**The demo isn't one page.** `HTML_FILES` in `generate_demo.py` lists
every page that gets copied and token-substituted:

- `index.html`, `booking.html` -- as before
- `styles/index.html` + six individual style pages (`custom-tattoos`,
  `fine-line-tattoos`, `black-and-grey-tattoos`, `realism-tattoos`,
  `traditional-tattoos`, `cover-up-tattoos`) -- separate, crawlable URLs
  for the terms people actually search, instead of one generic
  `/services` page. Copy is genuine general information about each
  style, not a claim that this specific shop specializes in it.
- `artists/index.html` -- states plainly that real artist profiles are
  added after onboarding. No fake names, bios, or portfolios; a demo can
  show *where* content will go without pretending it already exists.

Adding a page means adding one path to `HTML_FILES` -- canonical/`og:url`
tags and its `sitemap.xml` entry are computed automatically from that
path via `page_url()`/`page_tokens()`, no per-page wiring needed.

**Canonical URL, `og:url`, `robots.txt`, and `sitemap.xml` are only
generated when a site is actually hosted somewhere** -- pass
`--site-base-url https://your-domain.com` (or set `DEMO_SITE_BASE_URL` in
`.env`) once demo hosting exists (roadmap item in `ARCHITECTURE.md` §16).
Without it, those tags are omitted rather than pointing at a placeholder
domain -- a missing canonical is harmless; a wrong one actively hurts
indexing. Re-run with `--force` once a real base URL is set to backfill
already-generated demos.

This template is also the intended starting point for a client's real
site once a lead converts -- there's no separate "production site"
generator. Once real content exists, `onboarding_templates/` (sibling to
`template/`, never copied by `generate_demo.py`) has the artist-page
template with `Person` schema, meant to be hand-filled per real artist --
see that folder's README. What's still missing beyond that lives outside
the HTML entirely: Google Business Profile, reviews, and citation
consistency. That's a per-client manual process, not something this
script can do -- see the project-root `SEO_CHECKLIST.md`.

## Color palette: real, but never the real photo

`photo_palette.py` fetches one photo of the actual lead business live via
the Places API (New) Photo endpoint, computes a small hex color palette
from it in memory, and discards the image bytes immediately. Only the
derived colors get written anywhere -- never the photo itself.

This isn't a style choice, it's a Google Places API terms requirement:
photo content can't be cached or stored, only fetched live and displayed
with attribution
(https://developers.google.com/maps/documentation/places/web-service/policies).
General web scraping for photos was considered and ruled out for the same
reason this project moved off using Rooster Ink's real design as a
template -- reusing someone else's real content without permission, even
for a sales pitch, isn't something to build a pipeline around.

**Current status: not working, cause not yet identified.** Every lead
currently falls back to the template's default palette. Testing directly
against the Places API shows `200 OK` responses with the `photos` field
silently absent -- even for a landmark with heavy photo coverage
(Statue of Liberty), which rules out "this specific business has no
photos" as the explanation. Field mask syntax matches Google's
documented format (`photos` for Place Details, `places.photos` for Text
Search). Most likely cause is a Photos-specific enablement/SKU gap on the
Cloud project that isn't surfaced as an error -- worth checking API
metrics in Cloud Console for the actual request outcome, or Google
Cloud support, before spending more time debugging client-side. The
pipeline degrades safely in the meantime: every demo still generates
correctly with the template's default palette, nothing crashes or
produces broken output.

## Before this goes anywhere near a lead

This is a mockup, not a finished site, and it says so nowhere on the page
itself.

1. **Human review each one** before it's referenced in outreach.
2. **Be precise in the outreach message** about what this is -- a concept
   built to show what's possible, not a live production site.
3. **Check the lead is still actually qualified.** Same gap as the other
   pipeline stages: `generate_demo.py` only ever runs for
   `qualified_no_website`/`qualified_outdated` leads, so it won't build a
   *new* demo for one [reverify](../reverify) has since moved to
   `needs_review` or `disqualified_modern` -- but an **existing** demo,
   already sitting in `output/<slug>/`, doesn't know when that happens.
   Unlike the outreach draft and dossier, the demo's own content (name,
   address, phone, generic template copy) doesn't make any claim that
   goes false when a lead's status changes -- it never says "your current
   site is outdated," that pitch only lives in the outreach copy. So the
   demo file itself doesn't need the same in-file flag. What *is* worth
   checking: whether a demo existing at all for a lead is still a
   meaningful signal before referencing it — see
   [../outreach/README.md](../outreach/README.md#a-draft-can-go-stale-after-its-generated),
   [../reverify/README.md](../reverify/README.md#known-limitations), and
   [../approval_queue/README.md](../approval_queue/README.md#known-limitations)
   for the full picture (real example: Village Tattoo NYC).

## Known limitations

- No HTML/JSON escaping on inserted business names -- a name containing
  `&`, `<`, or `"` could produce slightly malformed markup or JSON-LD.
  Rare in practice for real business names, but untested.
- No images at all, by design -- see above. If real photography is ever
  wanted, it needs an explicit permission/licensing conversation with
  each lead, not an automated pipeline.
- Color palette personalization is currently non-functional (see above).
