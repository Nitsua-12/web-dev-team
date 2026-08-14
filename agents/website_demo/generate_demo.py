"""Website Demo Generation Agent.

Takes qualified leads from the Discovery Agent's leads.db and produces a
personalized copy of the neutral demo template (template/) for each one --
swapping in the real business name, address, phone, and a color palette
derived from that shop's real Google listing photo (see photo_palette.py;
the photo itself is never stored, only the extracted colors are).

This is a mockup, not a finished site. See README.md before using any of
this in real outreach.

Usage:
    python generate_demo.py --limit 3      # smoke test on first 3
    python generate_demo.py                # every qualified lead
    python generate_demo.py --no-palette    # skip photo/color lookup (faster, free)
"""

import argparse
import datetime
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

import photo_palette
from state_names import STATE_NAMES

DEFAULT_DB = Path(__file__).parent.parent / "discovery" / "leads.db"
DEFAULT_TEMPLATE_DIR = Path(__file__).parent / "template"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "output"
DEFAULT_INDEXABLE_SLUGS_FILE = Path(__file__).parent / "indexable_slugs.txt"

QUALIFYING_STATUSES = ("qualified_no_website", "qualified_outdated")

# Every page that ships in the demo. Paths are relative to template/, always
# forward-slash regardless of OS. Adding a page here is the only step needed
# for it to get token substitution, a canonical/og:url pair (once hosted),
# and a sitemap.xml entry -- see page_url() and write_sitemap().
HTML_FILES = [
    "index.html",
    "booking.html",
    "artists/index.html",
    "styles/index.html",
    "styles/custom-tattoos.html",
    "styles/fine-line-tattoos.html",
    "styles/black-and-grey-tattoos.html",
    "styles/realism-tattoos.html",
    "styles/traditional-tattoos.html",
    "styles/cover-up-tattoos.html",
]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def fetch_qualified_leads(db_path: Path, limit: int | None) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" for _ in QUALIFYING_STATUSES)
    query = f"SELECT * FROM leads WHERE qualification_status IN ({placeholders}) ORDER BY id"
    if limit:
        query += f" LIMIT {int(limit)}"
    rows = conn.execute(query, QUALIFYING_STATUSES).fetchall()
    conn.close()
    return rows


def slugify(business_name: str, city: str) -> str:
    raw = f"{business_name}-{city}"
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug or "lead"


def phone_to_e164(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return ""


def build_tokens(lead: sqlite3.Row, palette: dict | None) -> dict:
    name = lead["business_name"] or "This Shop"
    street = (lead["formatted_address"] or "").split(",")[0].strip()
    city = lead["city"] or ""
    state_abbr = (lead["state"] or "").upper()
    state_full = STATE_NAMES.get(state_abbr, state_abbr)
    phone = lead["phone"] or "(000) 000-0000"
    postal_code = lead["zip"] or ""

    if palette:
        style_block = (
            "<style>:root{"
            f"--accent:{palette['accent']};"
            f"--accent-dark:{palette['accent_dark']};"
            f"--accent-soft:{palette['accent_soft']};"
            "}</style>"
        )
    else:
        style_block = ""

    return {
        "BUSINESS_NAME": name,
        "STREET_ADDRESS": street or "Address on request",
        "CITY": city or "Your City",
        "STATE_ABBR": state_abbr,
        "CITY_STATE": ", ".join(p for p in [city, state_full] if p) or "Your City",
        "POSTAL_CODE": postal_code,
        "PHONE": phone,
        "PHONE_E164": phone_to_e164(phone),
        "YEAR": str(datetime.date.today().year),
        "PALETTE_STYLE_BLOCK": style_block,
    }


def read_indexable_slugs(path: Path) -> set[str]:
    """Slugs cleared to be indexed by search engines -- see ROBOTS_META_TAG
    in page_tokens(). One slug per line; a missing file or blank lines are
    tolerated, not errors -- "nothing cleared yet" is the correct starting
    state and looks the same as "file doesn't exist"."""
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def page_url(site_base_url: str, slug: str, html_file: str) -> str:
    """Absolute URL for one page. index.html files get a clean directory
    URL (trailing slash, no filename); every other page keeps its path."""
    base_dir = f"{site_base_url.rstrip('/')}/{slug}/"
    if html_file == "index.html":
        return base_dir
    if html_file.endswith("/index.html"):
        return base_dir + html_file[: -len("index.html")]
    return base_dir + html_file


def page_tokens(html_file: str, slug: str, site_base_url: str | None, indexable_slugs: set[str]) -> dict:
    """CANONICAL_TAG/OG_URL_TAG/JSONLD_URL_FIELD/ROBOTS_META_TAG for one
    specific page.

    CANONICAL_TAG/OG_URL_TAG/JSONLD_URL_FIELD need an absolute URL to be
    meaningful, which only exists once the demo is actually hosted
    somewhere (see README.md's Hosting section for how to set that up).
    Without site_base_url they render as nothing rather than pointing at a
    fake/placeholder domain -- a missing canonical is harmless, a wrong
    one actively hurts indexing.

    ROBOTS_META_TAG doesn't depend on hosting -- every demo defaults to
    noindex regardless, since these are unsolicited mockups sent to
    businesses that haven't agreed to anything. Only a slug explicitly
    listed in indexable_slugs (see read_indexable_slugs()) gets
    "index, follow", and only after that business has actually responded.
    """
    robots_content = "index, follow" if slug in indexable_slugs else "noindex"
    robots_tag = {"ROBOTS_META_TAG": f'<meta name="robots" content="{robots_content}">'}

    if not site_base_url:
        return {"CANONICAL_TAG": "", "OG_URL_TAG": "", "JSONLD_URL_FIELD": "", **robots_tag}

    url = page_url(site_base_url, slug, html_file)
    return {
        "CANONICAL_TAG": f'<link rel="canonical" href="{url}">',
        "OG_URL_TAG": f'<meta property="og:url" content="{url}">',
        "JSONLD_URL_FIELD": f',\n  "url": "{url}"',
        **robots_tag,
    }


def apply_tokens(text: str, tokens: dict) -> str:
    for key, value in tokens.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def write_sitemap(dest: Path, slug: str, site_base_url: str) -> None:
    """sitemap.xml needs an absolute site URL to be meaningful -- only
    called when one is configured, see page_tokens(). Unlike robots.txt
    (see deploy.py's build_root_robots_txt()), a sitemap doesn't need to
    live at a site's root, so a per-slug file here is correct as-is. This
    function used to also write a per-slug robots.txt, which never had
    any effect once hosted -- crawlers only ever read robots.txt at a
    site's actual root -- so that part has been removed."""
    today = datetime.date.today().isoformat()
    entries = "\n".join(
        f"  <url><loc>{page_url(site_base_url, slug, f)}</loc><lastmod>{today}</lastmod></url>"
        for f in HTML_FILES
    )
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        "</urlset>\n"
    )
    (dest / "sitemap.xml").write_text(sitemap, encoding="utf-8")


def generate_demo(
    lead: sqlite3.Row,
    template_dir: Path,
    output_dir: Path,
    force: bool,
    palette: dict | None,
    site_base_url: str | None,
    indexable_slugs: set[str],
) -> Path:
    slug = slugify(lead["business_name"], lead["city"] or "")
    dest = output_dir / slug

    if dest.exists() and not force:
        return dest

    if dest.exists():
        shutil.rmtree(dest)

    shutil.copytree(template_dir, dest)

    base_tokens = build_tokens(lead, palette)
    for html_file in HTML_FILES:
        path = dest / html_file
        if not path.exists():
            continue
        tokens = {**base_tokens, **page_tokens(html_file, slug, site_base_url, indexable_slugs)}
        original = path.read_text(encoding="utf-8")
        path.write_text(apply_tokens(original, tokens), encoding="utf-8")

    if site_base_url:
        write_sitemap(dest, slug, site_base_url)

    return dest


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Website Demo Generation Agent")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to Discovery Agent's leads.db")
    parser.add_argument("--template-dir", type=Path, default=DEFAULT_TEMPLATE_DIR, help="Source demo template")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Where to write per-lead demos")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N qualified leads")
    parser.add_argument("--force", action="store_true", help="Regenerate demos that already exist")
    parser.add_argument("--no-palette", action="store_true", help="Skip live photo/color lookup, use template defaults")
    parser.add_argument(
        "--site-base-url",
        default=os.environ.get("DEMO_SITE_BASE_URL", ""),
        help="Base URL demos are hosted at (e.g. https://demos.example.com). "
        "Enables canonical/og:url tags and per-lead sitemap.xml. "
        "Falls back to DEMO_SITE_BASE_URL in .env. Omit if you haven't set up "
        "Cloudflare Pages hosting yet -- see README.md's Hosting section.",
    )
    parser.add_argument(
        "--indexable-slugs-file",
        type=Path,
        default=DEFAULT_INDEXABLE_SLUGS_FILE,
        help="Plain text, one slug per line -- leads cleared to be indexed by "
        "search engines. Every demo defaults to noindex. See README.md.",
    )
    args = parser.parse_args()
    site_base_url = args.site_base_url.strip() or None
    indexable_slugs = read_indexable_slugs(args.indexable_slugs_file)

    if not args.db.exists():
        raise SystemExit(f"leads.db not found at {args.db} -- run the Discovery Agent first")
    if not args.template_dir.exists():
        raise SystemExit(f"Template directory not found at {args.template_dir}")

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    if not args.no_palette and not api_key:
        raise SystemExit("GOOGLE_PLACES_API_KEY not set -- add it to .env, or pass --no-palette to skip color matching")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    leads = fetch_qualified_leads(args.db, args.limit)
    print(f"{len(leads)} qualified lead(s) found")
    if not site_base_url:
        print("No --site-base-url / DEMO_SITE_BASE_URL set -- canonical/og:url tags "
              "and sitemap.xml will be omitted until you set one up (see README.md's "
              "Hosting section).")

    generated, skipped = 0, 0
    for lead in leads:
        slug = slugify(lead["business_name"], lead["city"] or "")
        pre_existing = (args.output_dir / slug).exists() and not args.force

        palette = None
        if not args.no_palette and not pre_existing:
            palette = photo_palette.get_palette(lead["google_place_id"], api_key)

        dest = generate_demo(lead, args.template_dir, args.output_dir, args.force, palette, site_base_url, indexable_slugs)

        palette_note = f" (accent {palette['accent']})" if palette else " (default palette)"
        if pre_existing:
            skipped += 1
            print(f"  {lead['business_name']} -> {dest} (already existed, skipped)")
        else:
            generated += 1
            print(f"  {lead['business_name']} -> {dest}{palette_note}")

    print(f"\nDone. {generated} generated, {skipped} skipped (already existed), output in {args.output_dir}")


if __name__ == "__main__":
    main()
