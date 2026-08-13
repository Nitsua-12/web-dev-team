# Demo Site Hosting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every generated demo site a real, working URL on Cloudflare Pages, with every demo defaulting to not-indexable-by-search-engines until a lead actually responds.

**Architecture:** All changes live inside the existing `agents/website_demo/` agent (no new agent, no new venv). `generate_demo.py` gains a noindex-by-default `robots` meta tag per page, driven by a plain-text `indexable_slugs.txt` allowlist. A new `deploy.py` builds a real root-level `robots.txt` from that same allowlist and uploads `output/` to Cloudflare Pages via the `wrangler` CLI (invoked through `npx`).

**Tech Stack:** Python 3 (stdlib `unittest`, `subprocess`), `python-dotenv` (already a dependency), Cloudflare Pages + `wrangler` CLI via `npx` (Node/npm already installed: v24.19.0 / 11.17.0).

## Global Constraints

- No new Python dependency — `deploy.py` uses only `subprocess`, `os`, `pathlib`, `sys`, and `python-dotenv` (already in `requirements.txt`).
- Windows environment: `npx` is a `.cmd` shim, not a directly-executable image — `subprocess.run([...])` must pass `shell=True` on Windows or it raises `FileNotFoundError`. Use `shell=(os.name == "nt")`.
- Every demo defaults to **not indexable** (`noindex`) regardless of hosting status — this is a deliberate default, not something any task should weaken or make opt-out.
- `indexable_slugs.txt` is operational state (real business slugs), not source — gitignored, same treatment as every `*.db` file in this repo (see root `.gitignore`'s "Local databases (operational state, not source)" comment block).
- `robots.txt` is only meaningful at a site's actual root — never write a per-subdirectory copy again (this is the bug being fixed; see spec §2).
- Tests use Python's stdlib `unittest`, matching every other agent in this project (no new test framework). Run via that agent's own venv: `agents/website_demo/.venv/Scripts/python.exe`.
- Full design context: [docs/superpowers/specs/2026-08-13-demo-site-hosting-design.md](../specs/2026-08-13-demo-site-hosting-design.md).

---

## Task 1: `read_indexable_slugs()` helper

**Files:**
- Modify: `agents/website_demo/generate_demo.py`
- Test: `agents/website_demo/test_generate_demo.py` (new file)

**Interfaces:**
- Produces: `read_indexable_slugs(path: Path) -> set[str]` (module-level function in `generate_demo.py`), `DEFAULT_INDEXABLE_SLUGS_FILE: Path` (module-level constant in `generate_demo.py`, value `Path(__file__).parent / "indexable_slugs.txt"`)

- [ ] **Step 1: Write the failing tests**

Create `agents/website_demo/test_generate_demo.py`:

```python
import tempfile
import unittest
from pathlib import Path

from generate_demo import read_indexable_slugs


class ReadIndexableSlugsTests(unittest.TestCase):
    def test_missing_file_returns_empty_set(self):
        missing = Path(tempfile.gettempdir()) / "definitely-does-not-exist-12345.txt"
        self.assertEqual(read_indexable_slugs(missing), set())

    def test_empty_file_returns_empty_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "indexable_slugs.txt"
            path.write_text("", encoding="utf-8")
            self.assertEqual(read_indexable_slugs(path), set())

    def test_populated_file_returns_slugs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "indexable_slugs.txt"
            path.write_text("village-tattoo-nyc\nink-and-iron-austin\n", encoding="utf-8")
            self.assertEqual(
                read_indexable_slugs(path),
                {"village-tattoo-nyc", "ink-and-iron-austin"},
            )

    def test_blank_lines_and_whitespace_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "indexable_slugs.txt"
            path.write_text("village-tattoo-nyc\n\n   \n  ink-and-iron-austin  \n", encoding="utf-8")
            self.assertEqual(
                read_indexable_slugs(path),
                {"village-tattoo-nyc", "ink-and-iron-austin"},
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd agents/website_demo && ./.venv/Scripts/python.exe -m unittest test_generate_demo.py -v
```
Expected: FAIL/ERROR — `ImportError: cannot import name 'read_indexable_slugs' from 'generate_demo'`

- [ ] **Step 3: Add `DEFAULT_INDEXABLE_SLUGS_FILE` constant**

In `generate_demo.py`, find:
```python
DEFAULT_DB = Path(__file__).parent.parent / "discovery" / "leads.db"
DEFAULT_TEMPLATE_DIR = Path(__file__).parent / "template"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "output"
```

Replace with:
```python
DEFAULT_DB = Path(__file__).parent.parent / "discovery" / "leads.db"
DEFAULT_TEMPLATE_DIR = Path(__file__).parent / "template"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "output"
DEFAULT_INDEXABLE_SLUGS_FILE = Path(__file__).parent / "indexable_slugs.txt"
```

- [ ] **Step 4: Implement `read_indexable_slugs()`**

In `generate_demo.py`, find the `page_url()` function definition:
```python
def page_url(site_base_url: str, slug: str, html_file: str) -> str:
```

Insert this new function immediately **before** it:
```python
def read_indexable_slugs(path: Path) -> set[str]:
    """Slugs cleared to be indexed by search engines -- see ROBOTS_META_TAG
    in page_tokens(). One slug per line; a missing file or blank lines are
    tolerated, not errors -- "nothing cleared yet" is the correct starting
    state and looks the same as "file doesn't exist"."""
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def page_url(site_base_url: str, slug: str, html_file: str) -> str:
```

(Only add the new function and its blank-line separator — leave the existing `page_url` definition and everything below it untouched.)

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd agents/website_demo && ./.venv/Scripts/python.exe -m unittest test_generate_demo.py -v
```
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add agents/website_demo/generate_demo.py agents/website_demo/test_generate_demo.py
git commit -m "Add read_indexable_slugs() helper for demo-hosting noindex allowlist"
```

---

## Task 2: Fix the noindex mechanism — `ROBOTS_META_TAG` + remove the broken per-slug `robots.txt`

**Files:**
- Modify: `agents/website_demo/generate_demo.py`
- Modify: `agents/website_demo/template/index.html`, `booking.html`, `artists/index.html`, `styles/index.html`, `styles/custom-tattoos.html`, `styles/fine-line-tattoos.html`, `styles/black-and-grey-tattoos.html`, `styles/realism-tattoos.html`, `styles/traditional-tattoos.html`, `styles/cover-up-tattoos.html`
- Test: `agents/website_demo/test_generate_demo.py`

**Interfaces:**
- Consumes: `read_indexable_slugs()`, `DEFAULT_INDEXABLE_SLUGS_FILE` (Task 1)
- Produces: `page_tokens(html_file: str, slug: str, site_base_url: str | None, indexable_slugs: set[str]) -> dict` (now includes a `"ROBOTS_META_TAG"` key; signature gains `indexable_slugs`), `write_sitemap(dest: Path, slug: str, site_base_url: str) -> None` (renamed from `write_seo_files`, no longer writes `robots.txt`), `generate_demo(..., indexable_slugs: set[str]) -> Path` (signature gains `indexable_slugs` as the new final parameter)

### Background this task depends on

Every template page currently has a **hardcoded, static** line in its `<head>`:
```html
<meta name="robots" content="index, follow">
```
This is the opposite of what's needed and is identical across all 10 files. This task replaces that static line with a `{{ROBOTS_META_TAG}}` token in every file, and makes `page_tokens()` compute its value: `noindex` by default, `index, follow` only when the lead's slug is in `indexable_slugs`.

- [ ] **Step 1: Write the failing tests**

Add to `agents/website_demo/test_generate_demo.py` (append after the existing `ReadIndexableSlugsTests` class, before the `if __name__ == "__main__":` line):

```python
from generate_demo import page_tokens, write_sitemap


class PageTokensRobotsTests(unittest.TestCase):
    def test_noindex_by_default(self):
        tokens = page_tokens("index.html", "some-slug", None, set())
        self.assertEqual(tokens["ROBOTS_META_TAG"], '<meta name="robots" content="noindex">')

    def test_index_follow_when_slug_cleared(self):
        tokens = page_tokens("index.html", "some-slug", None, {"some-slug"})
        self.assertEqual(tokens["ROBOTS_META_TAG"], '<meta name="robots" content="index, follow">')

    def test_other_slugs_not_cleared_by_a_different_slugs_clearance(self):
        tokens = page_tokens("index.html", "some-slug", None, {"a-different-slug"})
        self.assertEqual(tokens["ROBOTS_META_TAG"], '<meta name="robots" content="noindex">')

    def test_noindex_default_persists_even_with_site_base_url(self):
        tokens = page_tokens("index.html", "some-slug", "https://example.pages.dev", set())
        self.assertEqual(tokens["ROBOTS_META_TAG"], '<meta name="robots" content="noindex">')
        self.assertNotEqual(tokens["CANONICAL_TAG"], "")  # unaffected by the robots default


class WriteSitemapTests(unittest.TestCase):
    def test_writes_sitemap_but_not_robots_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            write_sitemap(dest, "some-slug", "https://example.pages.dev")
            self.assertTrue((dest / "sitemap.xml").exists())
            self.assertFalse((dest / "robots.txt").exists())
            sitemap_content = (dest / "sitemap.xml").read_text(encoding="utf-8")
            self.assertIn("https://example.pages.dev/some-slug/", sitemap_content)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd agents/website_demo && ./.venv/Scripts/python.exe -m unittest test_generate_demo.py -v
```
Expected: FAIL/ERROR — `ImportError: cannot import name 'write_sitemap'` (and `page_tokens()` still has the old 3-argument signature, so `PageTokensRobotsTests` will error too once the import succeeds)

- [ ] **Step 3: Update `page_tokens()`**

In `generate_demo.py`, find:
```python
def page_tokens(html_file: str, slug: str, site_base_url: str | None) -> dict:
    """CANONICAL_TAG/OG_URL_TAG/JSONLD_URL_FIELD for one specific page.

    These need an absolute URL to be meaningful, which only exists once the
    demo is actually hosted somewhere (not built yet -- see ARCHITECTURE.md
    roadmap). Without site_base_url they render as nothing rather than
    pointing at a fake/placeholder domain -- a missing canonical is
    harmless, a wrong one actively hurts indexing.
    """
    if not site_base_url:
        return {"CANONICAL_TAG": "", "OG_URL_TAG": "", "JSONLD_URL_FIELD": ""}

    url = page_url(site_base_url, slug, html_file)
    return {
        "CANONICAL_TAG": f'<link rel="canonical" href="{url}">',
        "OG_URL_TAG": f'<meta property="og:url" content="{url}">',
        "JSONLD_URL_FIELD": f',\n  "url": "{url}"',
    }
```

Replace with:
```python
def page_tokens(html_file: str, slug: str, site_base_url: str | None, indexable_slugs: set[str]) -> dict:
    """CANONICAL_TAG/OG_URL_TAG/JSONLD_URL_FIELD/ROBOTS_META_TAG for one
    specific page.

    CANONICAL_TAG/OG_URL_TAG/JSONLD_URL_FIELD need an absolute URL to be
    meaningful, which only exists once the demo is actually hosted
    somewhere (not built yet -- see ARCHITECTURE.md roadmap). Without
    site_base_url they render as nothing rather than pointing at a
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
```

- [ ] **Step 4: Rename `write_seo_files()` to `write_sitemap()` and remove the broken `robots.txt` write**

In `generate_demo.py`, find:
```python
def write_seo_files(dest: Path, slug: str, site_base_url: str) -> None:
    """robots.txt and sitemap.xml both need an absolute site URL to be
    meaningful -- only called when one is configured, see page_tokens()."""
    base = site_base_url.rstrip("/")
    sitemap_url = f"{base}/{slug}/sitemap.xml"

    (dest / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {sitemap_url}\n",
        encoding="utf-8",
    )

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
```

Replace with:
```python
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
```

- [ ] **Step 5: Update `generate_demo()` to thread `indexable_slugs` through**

In `generate_demo.py`, find:
```python
def generate_demo(
    lead: sqlite3.Row,
    template_dir: Path,
    output_dir: Path,
    force: bool,
    palette: dict | None,
    site_base_url: str | None,
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
        tokens = {**base_tokens, **page_tokens(html_file, slug, site_base_url)}
        original = path.read_text(encoding="utf-8")
        path.write_text(apply_tokens(original, tokens), encoding="utf-8")

    if site_base_url:
        write_seo_files(dest, slug, site_base_url)

    return dest
```

Replace with:
```python
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
```

- [ ] **Step 6: Wire `indexable_slugs` into `main()`**

In `generate_demo.py`, find the `--site-base-url` argparse block:
```python
    parser.add_argument(
        "--site-base-url",
        default=os.environ.get("DEMO_SITE_BASE_URL", ""),
        help="Base URL demos are hosted at (e.g. https://demos.example.com). "
        "Enables canonical/og:url tags and per-lead robots.txt + sitemap.xml. "
        "Falls back to DEMO_SITE_BASE_URL in .env. Omit until hosting exists -- "
        "see ARCHITECTURE.md roadmap.",
    )
    args = parser.parse_args()
    site_base_url = args.site_base_url.strip() or None
```

Replace with:
```python
    parser.add_argument(
        "--site-base-url",
        default=os.environ.get("DEMO_SITE_BASE_URL", ""),
        help="Base URL demos are hosted at (e.g. https://demos.example.com). "
        "Enables canonical/og:url tags and per-lead sitemap.xml. "
        "Falls back to DEMO_SITE_BASE_URL in .env. Omit until hosting exists -- "
        "see README.md's Hosting section.",
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
```

Then find the `generate_demo(...)` call inside the loop:
```python
        dest = generate_demo(lead, args.template_dir, args.output_dir, args.force, palette, site_base_url)
```

Replace with:
```python
        dest = generate_demo(lead, args.template_dir, args.output_dir, args.force, palette, site_base_url, indexable_slugs)
```

- [ ] **Step 7: Replace the static robots meta tag in all 10 template files**

In **each** of these 10 files:
- `agents/website_demo/template/index.html`
- `agents/website_demo/template/booking.html`
- `agents/website_demo/template/artists/index.html`
- `agents/website_demo/template/styles/index.html`
- `agents/website_demo/template/styles/custom-tattoos.html`
- `agents/website_demo/template/styles/fine-line-tattoos.html`
- `agents/website_demo/template/styles/black-and-grey-tattoos.html`
- `agents/website_demo/template/styles/realism-tattoos.html`
- `agents/website_demo/template/styles/traditional-tattoos.html`
- `agents/website_demo/template/styles/cover-up-tattoos.html`

find:
```html
    <meta name="robots" content="index, follow">
```

and replace with:
```html
    {{ROBOTS_META_TAG}}
```

(Same line in every file — line 9 as of this writing, directly below the `{{CANONICAL_TAG}}` line. Do not change anything else in these files.)

- [ ] **Step 8: Verify the replacement landed in all 10 files and the old text is gone**

Run:
```bash
grep -rl "ROBOTS_META_TAG" agents/website_demo/template/
```
Expected: exactly 10 file paths listed.

Run:
```bash
grep -rl 'content="index, follow"' agents/website_demo/template/
```
Expected: no output (no matches).

- [ ] **Step 9: Run tests to verify they pass**

Run:
```bash
cd agents/website_demo && ./.venv/Scripts/python.exe -m unittest test_generate_demo.py -v
```
Expected: PASS (8 tests total: 4 from Task 1, 4 new)

- [ ] **Step 10: Commit**

```bash
git add agents/website_demo/generate_demo.py agents/website_demo/test_generate_demo.py agents/website_demo/template/
git commit -m "Default every demo page to noindex, fix broken per-slug robots.txt"
```

---

## Task 3: `build_root_robots_txt()` in a new `deploy.py`

**Files:**
- Create: `agents/website_demo/deploy.py` (this task only adds the pure function + module docstring/imports; the full CLI comes in Task 4)
- Test: `agents/website_demo/test_deploy.py` (new file)

**Interfaces:**
- Produces: `build_root_robots_txt(indexable_slugs: set[str]) -> str` (module-level function in `deploy.py`)

- [ ] **Step 1: Write the failing tests**

Create `agents/website_demo/test_deploy.py`:

```python
import unittest

from deploy import build_root_robots_txt


class BuildRootRobotsTxtTests(unittest.TestCase):
    def test_no_indexable_slugs_disallows_everything(self):
        self.assertEqual(build_root_robots_txt(set()), "User-agent: *\nDisallow: /\n")

    def test_one_indexable_slug(self):
        result = build_root_robots_txt({"village-tattoo-nyc"})
        self.assertEqual(result, "User-agent: *\nDisallow: /\nAllow: /village-tattoo-nyc/\n")

    def test_multiple_indexable_slugs_sorted_for_determinism(self):
        result = build_root_robots_txt({"zzz-tattoo", "aaa-tattoo"})
        self.assertEqual(
            result,
            "User-agent: *\nDisallow: /\nAllow: /aaa-tattoo/\nAllow: /zzz-tattoo/\n",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd agents/website_demo && ./.venv/Scripts/python.exe -m unittest test_deploy.py -v
```
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'deploy'` (file doesn't exist yet)

- [ ] **Step 3: Create `deploy.py` with the module docstring and `build_root_robots_txt()`**

Create `agents/website_demo/deploy.py`:

```python
"""Demo Site Deploy Script.

Uploads agents/website_demo/output/ to Cloudflare Pages via the `wrangler`
CLI (invoked through `npx` -- no global install needed, just Node/npm).
Also writes a real root-level robots.txt reflecting indexable_slugs.txt
(see README.md's Hosting section). The per-slug robots.txt generate_demo.py
used to write never had any effect once hosted -- crawlers only ever read
robots.txt at a site's actual root, not inside a subdirectory -- see
build_root_robots_txt() below.

Usage:
    python deploy.py

Requires CLOUDFLARE_PROJECT_NAME, CLOUDFLARE_API_TOKEN, and
CLOUDFLARE_ACCOUNT_ID in .env -- see README.md's Hosting section for setup.
"""


def build_root_robots_txt(indexable_slugs: set[str]) -> str:
    """Real root-level robots.txt content -- Disallow everything by
    default (these are unsolicited mockups, see README.md), Allow only
    slugs a lead has actually responded to. Sorted for a deterministic,
    diffable file across repeated deploys."""
    lines = ["User-agent: *", "Disallow: /"]
    lines += [f"Allow: /{slug}/" for slug in sorted(indexable_slugs)]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd agents/website_demo && ./.venv/Scripts/python.exe -m unittest test_deploy.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/website_demo/deploy.py agents/website_demo/test_deploy.py
git commit -m "Add build_root_robots_txt() for real site-root robots.txt"
```

---

## Task 4: `deploy.py` CLI, config, and docs

**Files:**
- Modify: `agents/website_demo/deploy.py`
- Modify: `.gitignore` (repo root)
- Modify: `agents/website_demo/.env.example`
- Modify: `agents/website_demo/README.md`

**Interfaces:**
- Consumes: `read_indexable_slugs()`, `DEFAULT_INDEXABLE_SLUGS_FILE`, `DEFAULT_OUTPUT_DIR` (from `generate_demo.py`, Task 1/existing), `build_root_robots_txt()` (Task 3)
- Produces: a runnable `python deploy.py` CLI

This task has no new automated tests of its own — `deploy.py`'s remaining logic is CLI glue (env var checks, filesystem checks, a real subprocess call to `wrangler`) that isn't meaningfully unit-testable without mocking the exact thing being verified. It's verified for real in Task 5, matching this project's existing convention of verifying real external calls by actually exercising them rather than mocking. `build_root_robots_txt()` (the pure logic) already has full test coverage from Task 3.

- [ ] **Step 1: Add the CLI to `deploy.py`**

Replace the entire contents of `agents/website_demo/deploy.py` with:

```python
"""Demo Site Deploy Script.

Uploads agents/website_demo/output/ to Cloudflare Pages via the `wrangler`
CLI (invoked through `npx` -- no global install needed, just Node/npm).
Also writes a real root-level robots.txt reflecting indexable_slugs.txt
(see README.md's Hosting section). The per-slug robots.txt generate_demo.py
used to write never had any effect once hosted -- crawlers only ever read
robots.txt at a site's actual root, not inside a subdirectory -- see
build_root_robots_txt() below.

Usage:
    python deploy.py

Requires CLOUDFLARE_PROJECT_NAME, CLOUDFLARE_API_TOKEN, and
CLOUDFLARE_ACCOUNT_ID in .env -- see README.md's Hosting section for setup.
"""

import os
import subprocess
import sys

from dotenv import load_dotenv

from generate_demo import DEFAULT_INDEXABLE_SLUGS_FILE, DEFAULT_OUTPUT_DIR, read_indexable_slugs

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def build_root_robots_txt(indexable_slugs: set[str]) -> str:
    """Real root-level robots.txt content -- Disallow everything by
    default (these are unsolicited mockups, see README.md), Allow only
    slugs a lead has actually responded to. Sorted for a deterministic,
    diffable file across repeated deploys."""
    lines = ["User-agent: *", "Disallow: /"]
    lines += [f"Allow: /{slug}/" for slug in sorted(indexable_slugs)]
    return "\n".join(lines) + "\n"


def main() -> None:
    load_dotenv()

    if not DEFAULT_OUTPUT_DIR.exists() or not any(DEFAULT_OUTPUT_DIR.iterdir()):
        raise SystemExit(f"{DEFAULT_OUTPUT_DIR} is empty -- run generate_demo.py first")

    project_name = os.environ.get("CLOUDFLARE_PROJECT_NAME", "").strip()
    api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    missing = [
        name
        for name, value in (
            ("CLOUDFLARE_PROJECT_NAME", project_name),
            ("CLOUDFLARE_API_TOKEN", api_token),
            ("CLOUDFLARE_ACCOUNT_ID", account_id),
        )
        if not value
    ]
    if missing:
        raise SystemExit(f"{', '.join(missing)} not set -- add to .env, see README.md's Hosting section")

    indexable_slugs = read_indexable_slugs(DEFAULT_INDEXABLE_SLUGS_FILE)
    (DEFAULT_OUTPUT_DIR / "robots.txt").write_text(build_root_robots_txt(indexable_slugs), encoding="utf-8")
    print(
        f"robots.txt written -- {len(indexable_slugs)} indexable slug(s): "
        f"{', '.join(sorted(indexable_slugs)) or '(none)'}"
    )

    result = subprocess.run(
        ["npx", "wrangler", "pages", "deploy", str(DEFAULT_OUTPUT_DIR), "--project-name", project_name],
        shell=(os.name == "nt"),
    )
    if result.returncode != 0:
        raise SystemExit(f"wrangler deploy failed (exit code {result.returncode}) -- see output above")

    print(f"\nDeployed. Live at https://{project_name}.pages.dev")
    print(
        "Note: this reflects whatever was last generated -- re-run "
        "generate_demo.py --force first if a demo's content changed."
    )


if __name__ == "__main__":
    main()
```

This is a full-file replacement — it includes the `build_root_robots_txt()` function from Task 3 unchanged, plus the new imports, `sys.stdout.reconfigure` guard, and `main()`.

- [ ] **Step 2: Run the full test suite to confirm nothing broke**

Run:
```bash
cd agents/website_demo && ./.venv/Scripts/python.exe -m unittest discover -v
```
Expected: PASS (all tests from Tasks 1-3, no regressions)

- [ ] **Step 3: Gitignore `indexable_slugs.txt`**

In the repo-root `.gitignore`, find:
```
# Local databases (operational state, not source)
*.db
**/*.db
```

Replace with:
```
# Local databases (operational state, not source)
*.db
**/*.db
agents/website_demo/indexable_slugs.txt
```

- [ ] **Step 4: Add Cloudflare env vars to `.env.example`**

In `agents/website_demo/.env.example`, find:
```
GOOGLE_PLACES_API_KEY=
# Optional. Base URL demos are actually hosted at, e.g. https://demos.example.com
# Leave blank until demo hosting exists -- see ARCHITECTURE.md roadmap.
DEMO_SITE_BASE_URL=
```

Replace with:
```
GOOGLE_PLACES_API_KEY=
# Optional. Base URL demos are actually hosted at, e.g. https://demos.example.com
# Leave blank until demo hosting exists -- see README.md's Hosting section.
DEMO_SITE_BASE_URL=
# Required for deploy.py. Create a free Cloudflare account, a Pages
# project, and an API token -- see README.md's Hosting section.
CLOUDFLARE_PROJECT_NAME=
CLOUDFLARE_API_TOKEN=
CLOUDFLARE_ACCOUNT_ID=
```

- [ ] **Step 5: Update `README.md`'s "On-page SEO" section**

In `agents/website_demo/README.md`, find:
```markdown
**Canonical URL, `og:url`, `robots.txt`, and `sitemap.xml` are only
generated when a site is actually hosted somewhere** -- pass
`--site-base-url https://your-domain.com` (or set `DEMO_SITE_BASE_URL` in
`.env`) once demo hosting exists (roadmap item in `ARCHITECTURE.md` §16).
Without it, those tags are omitted rather than pointing at a placeholder
domain -- a missing canonical is harmless; a wrong one actively hurts
indexing. Re-run with `--force` once a real base URL is set to backfill
already-generated demos.
```

Replace with:
```markdown
**Canonical URL, `og:url`, and `sitemap.xml` are only generated when a
site is actually hosted somewhere** -- pass `--site-base-url
https://your-domain.com` (or set `DEMO_SITE_BASE_URL` in `.env`; see
"Hosting" below). Without it, those tags are omitted rather than pointing
at a placeholder domain -- a missing canonical is harmless; a wrong one
actively hurts indexing. Re-run with `--force` once a real base URL is
set to backfill already-generated demos.

**Every page also ships a `robots` meta tag, defaulting to `noindex`
regardless of hosting status** -- see "Hosting" below for why and how to
change it per lead. (`robots.txt` used to be written per-lead inside each
`output/<slug>/` folder, but that has no effect once hosted -- crawlers
only ever read `robots.txt` at a site's actual root. The real one is now
generated by `deploy.py` at deploy time.)
```

- [ ] **Step 6: Add a "Hosting" section to `README.md`**

In `agents/website_demo/README.md`, find the paragraph that ends the "On-page SEO" section:
```markdown
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
```

Replace with:
```markdown
This template is also the intended starting point for a client's real
site once a lead converts -- there's no separate "production site"
generator. Once real content exists, `onboarding_templates/` (sibling to
`template/`, never copied by `generate_demo.py`) has the artist-page
template with `Person` schema, meant to be hand-filled per real artist --
see that folder's README. What's still missing beyond that lives outside
the HTML entirely: Google Business Profile, reviews, and citation
consistency. That's a per-client manual process, not something this
script can do -- see the project-root `SEO_CHECKLIST.md`.

## Hosting

Demos are hosted on [Cloudflare Pages](https://pages.cloudflare.com/)
(free tier). One-time setup:

1. Create a free Cloudflare account.
2. Create a Pages project (pick a name -- your demos will live at
   `https://<that-name>.pages.dev`).
3. Create an API token with Pages edit permission.
4. Add to `.env`: `CLOUDFLARE_PROJECT_NAME`, `CLOUDFLARE_API_TOKEN`,
   `CLOUDFLARE_ACCOUNT_ID`, and set
   `DEMO_SITE_BASE_URL=https://<project-name>.pages.dev`.

Then:

```
python generate_demo.py --force   # regenerate demos with the real base URL
python deploy.py                  # upload output/ to Cloudflare Pages
```

`deploy.py` uses Cloudflare's own `wrangler` CLI via `npx` -- no global
install needed, just Node/npm on your machine.

### Noindex by default

These are unsolicited concept mockups sent to businesses that haven't
agreed to anything. Every demo defaults to **not indexable by search
engines** -- a shop's real customers should never stumble onto a mockup
the shop didn't make or ask for. The direct link still works fine for
outreach; it just won't show up in search results.

Two mechanisms enforce this together:

1. A `<meta name="robots" content="noindex">` tag on every page (see
   `ROBOTS_META_TAG` in `page_tokens()`), which is what actually keeps a
   page out of search results even if it's linked from elsewhere.
2. A real root-level `robots.txt`, written by `deploy.py` from
   `indexable_slugs.txt`, blocking crawling of everything except
   explicitly-cleared slugs.

**Once a lead actually responds** and it's appropriate for their demo to
be findable, clear it:

```
echo <their-slug> >> indexable_slugs.txt
python generate_demo.py --force    # regenerate every demo (cheap, no LLM calls);
                                    # only the newly-cleared one's tag actually changes
python deploy.py                   # redeploy with the updated robots.txt
```

`indexable_slugs.txt` is plain text, one slug per line, gitignored (it's
operational state -- real business slugs -- not source, same treatment as
every `.db` file in this project). A missing file is treated as "nothing
cleared yet," not an error.

## Color palette: real, but never the real photo
```

- [ ] **Step 7: Commit**

```bash
git add agents/website_demo/deploy.py .gitignore agents/website_demo/.env.example agents/website_demo/README.md
git commit -m "Add deploy.py CLI, Cloudflare config, and hosting docs"
```

---

## Task 5: Real Cloudflare setup, live deploy, and browser verification

**This task requires the user, not an autonomous agent, to complete the account-creation and credential steps** — creating third-party accounts and handling API tokens/credentials is outside what an agent should do unattended. Whoever executes this task should stop and hand the account-setup steps back to the user, then resume once `.env` is populated.

**Files:** none (verification only)

- [ ] **Step 1 (user): Create the Cloudflare account and Pages project**

1. Go to https://dash.cloudflare.com/sign-up and create a free account.
2. In the dashboard, create a Pages project (Workers & Pages → Create → Pages → "Direct Upload" — no need to connect a git repo). Pick a project name, e.g. `tattoo-outreach-demos`.
3. Create an API token: My Profile → API Tokens → Create Token → use the "Edit Cloudflare Workers" template or a custom token scoped to `Account.Cloudflare Pages: Edit`.
4. Note the Account ID, shown on the right sidebar of the dashboard's overview page.

- [ ] **Step 2 (user): Populate `.env`**

In `agents/website_demo/.env`, set:
```
CLOUDFLARE_PROJECT_NAME=<the project name chosen above>
CLOUDFLARE_API_TOKEN=<the token created above>
CLOUDFLARE_ACCOUNT_ID=<the account ID from the dashboard>
DEMO_SITE_BASE_URL=https://<the project name chosen above>.pages.dev
```

- [ ] **Step 3: Regenerate demos with the real base URL**

Run:
```bash
cd agents/website_demo && ./.venv/Scripts/python.exe generate_demo.py --force
```
Expected: every existing demo regenerates; console output shows no errors.

- [ ] **Step 4: Deploy**

Run:
```bash
cd agents/website_demo && ./.venv/Scripts/python.exe deploy.py
```
Expected: `wrangler`'s own progress output streams to the console, ending with a success message and this script's own `Deployed. Live at https://<project-name>.pages.dev` line.

If `wrangler` prompts interactively about authentication instead of using `CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID` from the environment: confirm both env vars are actually set in `.env` (Step 2) and that `deploy.py` was run from a shell where `load_dotenv()` can find that `.env` file (i.e. run from within `agents/website_demo/`, as shown above).

- [ ] **Step 5: Verify live in a browser — a non-cleared demo stays noindex**

Using the browser tool, navigate to `https://<project-name>.pages.dev/<any-slug>/` for any lead not in `indexable_slugs.txt`.

Confirm:
- The page loads and renders correctly (not a 404, not a Cloudflare error page).
- View page source (or inspect the DOM) and confirm `<meta name="robots" content="noindex">` is present in `<head>`.

- [ ] **Step 6: Verify the real root `robots.txt`**

Navigate to `https://<project-name>.pages.dev/robots.txt`.

Confirm the content is:
```
User-agent: *
Disallow: /
```
(assuming `indexable_slugs.txt` is still empty at this point — no `Allow:` lines yet).

- [ ] **Step 7: Verify the indexable-flip workflow end-to-end**

1. Pick any one real slug from `agents/website_demo/output/`. Run:
   ```bash
   echo <that-slug> >> agents/website_demo/indexable_slugs.txt
   ```
2. Regenerate and redeploy:
   ```bash
   cd agents/website_demo && ./.venv/Scripts/python.exe generate_demo.py --force && ./.venv/Scripts/python.exe deploy.py
   ```
3. In the browser, navigate to `https://<project-name>.pages.dev/<that-slug>/`, view source, and confirm the tag now reads `<meta name="robots" content="index, follow">`.
4. Navigate to `https://<project-name>.pages.dev/robots.txt` and confirm it now includes `Allow: /<that-slug>/`.
5. Navigate to a *different* slug (still not cleared) and confirm its tag still reads `noindex` — flipping one lead didn't affect the others.

- [ ] **Step 8: Clean up the test flip (optional but recommended)**

If the slug used in Step 7 was only for verification and shouldn't actually be indexable yet, remove it from `indexable_slugs.txt` and re-run `generate_demo.py --force && deploy.py` to restore it to `noindex`.

- [ ] **Step 9: Update ARCHITECTURE.md**

In `ARCHITECTURE.md`, update roadmap item #2 in the "Production roadmap — not yet built" list (§16) to reflect that demo hosting is now built, following the same "close out the gap" pattern used for prior completed roadmap items (see the `~~...~~ — **Resolved.**` treatment already used elsewhere in that file, e.g. §17's bottleneck table and §18's future-improvements list). Move it out of "not yet built" and into the "MVP — done today" list with a short description of what shipped (Cloudflare Pages, noindex-by-default, `indexable_slugs.txt` flip workflow).

- [ ] **Step 10: Commit**

```bash
git add ARCHITECTURE.md
git commit -m "Mark demo hosting as built in ARCHITECTURE.md roadmap"
```

(Do not commit `.env` or `indexable_slugs.txt` — both are gitignored as of Task 4, Step 3.)
