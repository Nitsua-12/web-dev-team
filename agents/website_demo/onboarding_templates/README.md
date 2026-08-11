# Onboarding Templates (Phase 2 — real clients only)

**Not part of the automated demo pipeline.** `generate_demo.py` never reads
this folder — nothing here is copied into `output/<slug>/` for a cold
lead. These are hand-filled once a lead actually converts and provides
their own real content, per `SEO_CHECKLIST.md`'s Phase 2 content intake.

## Why these are separate from `template/`

`template/` (the demo) has to stay truthful with zero client input, which
means no artist names, bios, or portfolio images can exist there — see
`template/artists/index.html`'s placeholder copy and
`website_demo/README.md`'s on-page SEO section. These onboarding
templates are the opposite: they assume real, client-provided content
exists and are built to hold it, with schema (`Person`, image alt text)
that would be actively wrong to publish about a business that hasn't
confirmed any of it.

## artist-page.html

One real artist per copy. Process:

1. Copy this file into the client's real site at `artists/<artist-slug>.html`
   (sibling to the demo's `artists/index.html`, once that page is updated
   to link to real artist pages instead of the placeholder note).
2. Fill in `{{ARTIST_NAME}}`, `{{ARTIST_BIO}}`, `{{ARTIST_SPECIALTIES}}`,
   `{{ARTIST_EXPERIENCE}}`, `{{ARTIST_INSTAGRAM_URL}}`,
   `{{ARTIST_INSTAGRAM_HANDLE}}` from the client's content intake answers
   — see `SEO_CHECKLIST.md` Phase 2. Don't write bio copy on an artist's
   behalf without them reviewing it before it publishes.
3. Replace the `{{ARTIST_PORTFOLIO_IMAGES}}` comment block with real
   `<figure>`/`<img>` markup — only for images the client has confirmed
   permission to use publicly. Descriptive filenames and alt text are
   part of the template comment; follow that pattern
   (`black-and-grey-sleeve-tattoo-<city-slug>.jpg`, not `IMG_1234.jpg`),
   and compress/convert to WebP before publishing.
4. Fill `{{ARTIST_CANONICAL_URL}}`, `{{BUSINESS_CANONICAL_URL}}`,
   `{{ARTIST_PHOTO_URL}}` once the real hosting domain is known.

**Reusable shortcut:** `{{BUSINESS_NAME}}`, `{{STREET_ADDRESS}}`,
`{{PHONE}}`, `{{CITY_STATE}}`, `{{YEAR}}`, and `{{PALETTE_STYLE_BLOCK}}`
use the exact same token names `generate_demo.py`'s `build_tokens()`
already produces for that lead's row in `leads.db` — running this file
through `apply_tokens(text, build_tokens(lead, palette))` fills those in
automatically from real Discovery data, leaving only the `ARTIST_*` and
canonical-URL tokens to fill by hand. There's no script wired up for
this yet since it's a one-off per converted client, not a batch
operation — build one only if/when there's enough real-client volume to
justify it.

## Once real artist pages exist

Update the demo→real-site copy's `artists/index.html` to list them (real
names linking to their real pages) instead of the onboarding placeholder
note, and update `styles/*.html` pages' onboarding-note blocks to link to
the artists who actually work in that style. Both are manual edits at
that point — the client's site is no longer a generated demo, it's their
real site.
