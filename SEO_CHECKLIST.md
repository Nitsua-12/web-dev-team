# Local SEO Checklist — Tattoo Shops

For a tattoo shop, ranking for "tattoo shop near me" or a style-specific
search takes three layers, in this order of leverage: what Google
directly indexes about the business (Phase 3), what the site itself
proves about the business (Phase 2), and the technical plumbing under
both (Phase 1). This project automates Phase 1 fully today. Phase 2 is
half-automated (page structure exists; content is client-supplied).
Phase 3 is entirely manual, per client, and always will be — see "Why
this isn't an agent" at the bottom.

A generated site can be technically perfect and still rank nowhere if it
has no artist pages, no style pages, and no real portfolio content —
technical SEO is necessary, not sufficient, for a visual,
personality-driven business like a tattoo shop.

**This checklist is about the site we build.** A separate, earlier step —
[`agents/discovery/site_audit.py`](agents/discovery/site_audit.py) —
already diagnoses the lead's *current* site before they're even a
client: real PageSpeed Insights/Core Web Vitals data plus on-page SEO and
conversion checks (missing title/meta, no schema, no phone number
visible, no CTA, etc.), stored per lead in `leads.db`'s `audit_signals`
column for any `qualified_outdated` lead. That's diagnostic input, not
duplicate work — Phase 2 below should start from what the audit actually
found broken, not treat this checklist as a generic substitute for
closing the loop on it.

## Phase 1 — Automated demo website (done, zero client input required)

Every lead's generated demo already ships with:

- [x] Title tags, meta descriptions, `robots` meta
- [x] Open Graph + Twitter Card tags
- [x] `LocalBusiness` JSON-LD (name, phone, full address including zip)
- [x] Canonical URL, `robots.txt`, `sitemap.xml` (activate automatically
      once `--site-base-url` is set — see `agents/website_demo/README.md`)
- [x] Style pages (`/styles/custom-tattoos.html`,
      `/fine-line-tattoos.html`, `/black-and-grey-tattoos.html`,
      `/realism-tattoos.html`, `/traditional-tattoos.html`,
      `/cover-up-tattoos.html`) — separate, crawlable URLs for the terms
      people actually search ("fine line tattoo artist near me"), not
      one generic `/services` page. Copy is genuine general information
      about each style, not a claim that this specific shop specializes
      in it.
- [x] An artists page (`/artists/`) that states real profiles are added
      after onboarding, rather than fabricating names or bios
- [x] Internal linking: homepage → style pages, homepage → artists page,
      style pages → booking, footer links across all pages

**Deliberately not done at this stage:** anything requiring a claim
about this specific business that Discovery didn't verify — no fake
artist names, specialties, years of experience, portfolio images,
reviews, or awards. A demo can show *where* content will go without
pretending the content already exists.

## Phase 2 — Client content onboarding (after a lead converts)

The page structure is built (`onboarding_templates/artist-page.html`,
`template/artists/` and `template/styles/` on the real site); it needs
real content from the client before it's honest to publish. Run this
intake once a lead signs.

### Before the content intake

- [ ] Pull this lead's `audit_signals` from `leads.db` (if it has one —
      only `qualified_outdated` leads get audited) and check off what the
      real site build actually fixes: was Core Web Vitals/performance
      genuinely addressed by the new template, is there now a real
      `LocalBusiness` schema block, a visible phone number, a real CTA?
      The point of selling against a diagnosed problem is closing the
      loop on that exact problem, not just shipping a generically good
      site and hoping it happens to cover the same ground.

### Content intake — ask the client for:

**Business**
- [ ] Preferred business description (their words, not invented)
- [ ] Service area (only areas they genuinely serve — see Location
      pages caution below)
- [ ] Booking process specifics, walk-in availability

**Per artist**
- [ ] Name, bio (their words, reviewed by them before publishing)
- [ ] Styles/specialties they actually work in
- [ ] Years tattooing, certifications if any
- [ ] Instagram/social profile links

**Portfolio**
- [ ] Explicit permission to publish each image
- [ ] Style category per image, for placement on the right style page
- [ ] Descriptive filenames and alt text (see Image SEO below) —
      `black-and-grey-sleeve-tattoo-st-louis.jpg`, not `IMG_3948.jpg`
- [ ] Before/after pairs for cover-up work, if they want to show it

**Services**
- [ ] Which styles to actually list (don't publish all six style pages
      as "offered" if the shop only does two of them)
- [ ] Piercing availability, if applicable
- [ ] Whether pricing should be public at all

### Once content is in hand

- [ ] Fill `onboarding_templates/artist-page.html` per artist (see that
      folder's README) — includes `Person` schema referencing the same
      business identity as the site's `LocalBusiness` schema
- [ ] Replace each style page's onboarding-note block with real
      portfolio examples and which artists work in that style
- [ ] Link artist pages ↔ style pages both directions (an artist's page
      links to the styles they work in; a style page links to the
      artists who do it) — this cross-linking is a real ranking lever,
      not just navigation
- [ ] Compress images, convert to WebP
- [ ] **Location pages** — only if the shop genuinely serves multiple
      distinct areas (e.g., a shop near a metro boundary that regularly
      draws clients from a named neighboring city). Do not create pages
      for cities the shop doesn't actually serve; Google detects and
      penalizes fabricated local relevance, and it undermines the trust
      this whole approach is built on.
- [ ] `Review` schema — only once real reviews are legitimately
      displayed on the site itself, not fabricated or copied from
      elsewhere

## Phase 3 — Local authority (manual, per client, ongoing)

This is what actually drives "someone searches for a tattoo shop near
them and finds this client" — a perfectly built site with no Google
Business Profile and no reviews still won't rank.

### Google Business Profile (highest-leverage item by far)

- [ ] Claim or verify the listing (it likely already exists from
      Google's own index — that's how Discovery found the lead)
- [ ] Primary category "Tattoo shop"; add "Body piercing shop" if
      applicable
- [ ] NAP (name/address/phone) matches the site **exactly** — same
      formatting, not just the same information
- [ ] Hours current, including holidays
- [ ] Website field points at the real site once hosted
- [ ] 5–10+ real photos uploaded by the client through their own GBP
      account — this project never sources or stores business photos
      (see `agents/website_demo/README.md`'s photo/ToS section); GBP is
      the one place real photos belong, and they have to come from the
      client
- [ ] Description field, written plainly, no keyword-stuffing
- [ ] Attributes filled in (walk-ins welcome, accessibility, payment
      types — whatever's actually true)

### Reviews

- [ ] Client knows how to respond to reviews (short, genuine, no
      template)
- [ ] A low-effort ask mechanism: a card or text template inviting past
      clients to leave a Google review, with a direct link
- [ ] No incentivized/paid reviews — against Google's terms and a fast
      way to get a listing penalized

### NAP consistency across the web

- [ ] Same exact name/address/phone format on GBP, the site, and any
      existing directory listings (Yelp, Facebook, Instagram bio, local
      directories)
- [ ] Fix or flag stale listings (old address, disconnected phone) —
      these actively hurt more than having no listing at all

### Citations and backlinks (lower priority)

- [ ] Presence on 2–3 general directories (Yelp, Facebook) — don't chase
      dozens of low-quality directories; that's dated and carries spam
      risk with little remaining SEO value
- [ ] Local backlinks (a chamber of commerce, a local press mention, a
      convention the shop attended) opportunistically, not manufactured

## Priority order across all three phases

1. Google Business Profile
2. Reviews
3. Real photos (via GBP, client-uploaded)
4. Correct NAP everywhere
5. The website itself, with genuine city + style relevance (Phase 1,
   done)
6. Individual artist pages (Phase 2)
7. Style pages with real portfolio content (Phase 2, structure done)
8. Internal linking between artists ↔ styles (Phase 2)
9. Local backlinks
10. Citations
11. Blog content, social signals (not started, lowest leverage of this
    list)

## Image SEO (visual businesses live or die on this)

- Descriptive filenames: `black-and-grey-sleeve-tattoo-st-louis.jpg`,
  not `IMG_3948.jpg`
- Alt text describing the actual tattoo, style, and shop/city — not
  keyword-stuffed
- Compress before publishing; prefer WebP
- Only images the client has confirmed permission to use — see Phase 2
  intake

## Why Phase 3 isn't an agent

Every Phase 3 item requires the client's own account credentials
(their Google Business Profile login, their Yelp login) or their own
direct action (asking their customers for reviews, uploading their own
photos). This project's agents never handle credentials or act on a
client's behalf in an external account — see `ARCHITECTURE.md` §11
(security) and §13 (legal/ethical: no scraping, no cloning, no
fabrication). Automating this would mean either storing client
credentials or requesting Google OAuth access per future client — both a
different, bigger project than generating a demo site, not worth
building before there's a single paying client to justify it.

**What could be built later, once there's real client volume:** a
lightweight tracker for which Phase 2/3 items are done per client and
who's overdue on a review ask — a checklist-state problem, not a
Google-automation problem.
