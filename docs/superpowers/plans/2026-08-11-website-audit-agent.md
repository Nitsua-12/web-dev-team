# Website Audit Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend Discovery's `qualified_outdated` leads with a real audit — PageSpeed Insights performance/Core Web Vitals data plus deterministic on-page SEO and conversion-signal checks — so Outreach/Dossier can cite specific findings instead of a generic "your site looks outdated" claim.

**Architecture:** Two new sibling modules in `agents/discovery/`: `psi_client.py` (thin PSI v5 API wrapper, mirrors the retry pattern already in `places_client.py`) and `site_audit.py` (HTML-based on-page SEO/conversion parsers, plus the `audit_site()` orchestrator that ties fetch + parsers + PSI together). `discovery_agent.py` calls `site_audit.audit_site()` once per lead, only when that lead's `qualification_status` is `qualified_outdated`. Results land in four new columns on the existing `leads` table via a migration that's safe to run against the real, already-populated `leads.db`.

**Tech Stack:** Python 3, `httpx` (already a dependency — no new packages), stdlib `unittest` for tests (this project has no existing test framework; `unittest` ships with Python so it adds zero new dependencies while still giving the pure-parsing and network-retry logic real automated coverage, consistent with the project's existing "verify against real output" ethos for everything else).

## Global Constraints

- Zero LLM calls anywhere in this feature (matches Discovery's existing zero-LLM design).
- Zero new paid dependencies — PageSpeed Insights and CrUX are free, quota-limited APIs, not billed (spec §8).
- The audit runs **only** for leads where `qualification_status == "qualified_outdated"` — never for `qualified_no_website` (nothing to audit) or `disqualified_modern` (never contacted) (spec §4).
- `site_check.py`'s existing qualification behavior must not change — it continues to decide `qualified_outdated` vs. `disqualified_modern` exactly as it does today (spec §4 non-goal).
- Any PSI failure must not crash the batch — record `audit_status = 'error'` and continue (spec §7).
- The existing `leads.db` (10 real leads, already used by Outreach/Dossier) must survive schema changes with no data loss — migration must be additive-only and idempotent.
- No prospect-scoring formula in this feature — `audit_score` is the raw PSI performance score (0–100), not a weighted composite (spec §2, §10).

---

### Task 1: PSI response parser (`psi_client.parse_pagespeed_result`)

**Files:**
- Create: `agents/discovery/psi_client.py`
- Test: `agents/discovery/test_psi_client.py`

**Interfaces:**
- Produces: `parse_pagespeed_result(raw: dict) -> dict` returning `{"performance_score": int|None, "lcp_ms": float|None, "cls": float|None, "viewport_ok": bool|None, "field_lcp_category": str|None, "field_cls_category": str|None, "field_inp_category": str|None, "has_field_data": bool}`

This is a pure function — no network — so it's tested first, against realistic fixture JSON matching PageSpeed Insights v5's documented response shape (`lighthouseResult.categories.performance.score` is a 0–1 float; `lighthouseResult.audits['largest-contentful-paint'].numericValue` is milliseconds; `lighthouseResult.audits['cumulative-layout-shift'].numericValue` is unitless; `lighthouseResult.audits['viewport'].score` is 1 or 0; `loadingExperience.metrics.*.category` is CrUX field data, present only for sites with enough real-world traffic history — small local-business sites often lack it entirely, which is why `has_field_data` exists).

- [ ] **Step 1: Write the failing tests**

```python
# agents/discovery/test_psi_client.py
import unittest

import psi_client

FIXTURE_WITH_FIELD_DATA = {
    "lighthouseResult": {
        "categories": {"performance": {"score": 0.42}},
        "audits": {
            "largest-contentful-paint": {"numericValue": 4123.5, "displayValue": "4.1 s"},
            "cumulative-layout-shift": {"numericValue": 0.15, "displayValue": "0.15"},
            "viewport": {"score": 1},
        },
    },
    "loadingExperience": {
        "metrics": {
            "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 4200, "category": "SLOW"},
            "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 12, "category": "AVERAGE"},
            "INTERACTION_TO_NEXT_PAINT": {"percentile": 300, "category": "AVERAGE"},
        }
    },
}

FIXTURE_WITHOUT_FIELD_DATA = {
    "lighthouseResult": {
        "categories": {"performance": {"score": 0.88}},
        "audits": {
            "largest-contentful-paint": {"numericValue": 1200.0, "displayValue": "1.2 s"},
            "cumulative-layout-shift": {"numericValue": 0.01, "displayValue": "0.01"},
            "viewport": {"score": 1},
        },
    },
    # no loadingExperience key at all -- realistic for a low-traffic small-business site
}


class ParsePagespeedResultTests(unittest.TestCase):
    def test_full_data(self):
        result = psi_client.parse_pagespeed_result(FIXTURE_WITH_FIELD_DATA)
        self.assertEqual(result["performance_score"], 42)
        self.assertEqual(result["lcp_ms"], 4123.5)
        self.assertEqual(result["cls"], 0.15)
        self.assertTrue(result["viewport_ok"])
        self.assertEqual(result["field_lcp_category"], "SLOW")
        self.assertEqual(result["field_cls_category"], "AVERAGE")
        self.assertEqual(result["field_inp_category"], "AVERAGE")
        self.assertTrue(result["has_field_data"])

    def test_no_field_data(self):
        result = psi_client.parse_pagespeed_result(FIXTURE_WITHOUT_FIELD_DATA)
        self.assertEqual(result["performance_score"], 88)
        self.assertFalse(result["has_field_data"])
        self.assertIsNone(result["field_lcp_category"])
        self.assertIsNone(result["field_cls_category"])
        self.assertIsNone(result["field_inp_category"])

    def test_missing_performance_category(self):
        result = psi_client.parse_pagespeed_result({"lighthouseResult": {"categories": {}, "audits": {}}})
        self.assertIsNone(result["performance_score"])
        self.assertIsNone(result["lcp_ms"])
        self.assertIsNone(result["viewport_ok"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/discovery && .venv\Scripts\python -m unittest test_psi_client -v`
Expected: FAIL — `ModuleNotFoundError` or `AttributeError: module 'psi_client' has no attribute 'parse_pagespeed_result'` (the file doesn't exist yet).

- [ ] **Step 3: Write the implementation**

```python
# agents/discovery/psi_client.py
"""Thin wrapper around Google's PageSpeed Insights v5 API (runPagespeed).

Free, quota-limited (not billed) -- see
https://developers.google.com/speed/docs/insights/v5/get-started.
Mirrors the retry/backoff pattern already used in places_client.py so
there's one retry implementation style across Discovery's API clients.
"""

import time

import httpx

PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


class PsiApiError(RuntimeError):
    pass


def parse_pagespeed_result(raw: dict) -> dict:
    """Extract the fields site_audit.py cares about from a raw PSI v5
    response. Pure function, no network -- takes the already-fetched JSON."""
    lighthouse = raw.get("lighthouseResult", {})
    audits = lighthouse.get("audits", {})
    categories = lighthouse.get("categories", {})

    performance_score = categories.get("performance", {}).get("score")
    performance_score_pct = round(performance_score * 100) if performance_score is not None else None

    lcp_audit = audits.get("largest-contentful-paint", {})
    cls_audit = audits.get("cumulative-layout-shift", {})
    viewport_audit = audits.get("viewport", {})

    metrics = raw.get("loadingExperience", {}).get("metrics", {})

    return {
        "performance_score": performance_score_pct,
        "lcp_ms": lcp_audit.get("numericValue"),
        "cls": cls_audit.get("numericValue"),
        "viewport_ok": (viewport_audit.get("score") == 1) if "score" in viewport_audit else None,
        "field_lcp_category": metrics.get("LARGEST_CONTENTFUL_PAINT_MS", {}).get("category"),
        "field_cls_category": metrics.get("CUMULATIVE_LAYOUT_SHIFT_SCORE", {}).get("category"),
        "field_inp_category": metrics.get("INTERACTION_TO_NEXT_PAINT", {}).get("category"),
        "has_field_data": bool(metrics),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/discovery && .venv\Scripts\python -m unittest test_psi_client -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/discovery/psi_client.py agents/discovery/test_psi_client.py
git commit -m "Add PageSpeed Insights response parser"
```

---

### Task 2: PSI API client with retry (`psi_client.run_pagespeed`)

**Files:**
- Modify: `agents/discovery/psi_client.py`
- Modify: `agents/discovery/test_psi_client.py`

**Interfaces:**
- Consumes: `PsiApiError` (Task 1)
- Produces: `run_pagespeed(url: str, api_key: str, max_retries: int = 3, client: httpx.Client | None = None) -> dict` — returns the raw parsed JSON on success, raises `PsiApiError` on exhausted retries or a non-retryable status. The optional `client` parameter exists solely so tests can inject an `httpx.Client` backed by `httpx.MockTransport` instead of hitting the real network — production callers never pass it.

- [ ] **Step 1: Write the failing tests**

```python
# append to agents/discovery/test_psi_client.py
from unittest.mock import patch

import httpx


class RunPagespeedTests(unittest.TestCase):
    def test_returns_json_on_200(self):
        def handler(request):
            return httpx.Response(200, json={"lighthouseResult": {}})
        client = httpx.Client(transport=httpx.MockTransport(handler))
        result = psi_client.run_pagespeed("https://example.com", "fake-key", client=client)
        self.assertEqual(result, {"lighthouseResult": {}})

    @patch("psi_client.time.sleep")
    def test_retries_on_429_then_succeeds(self, _mock_sleep):
        calls = {"count": 0}

        def handler(request):
            calls["count"] += 1
            if calls["count"] < 3:
                return httpx.Response(429, text="rate limited")
            return httpx.Response(200, json={"ok": True})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        result = psi_client.run_pagespeed("https://example.com", "fake-key", max_retries=3, client=client)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls["count"], 3)

    @patch("psi_client.time.sleep")
    def test_raises_after_exhausting_retries(self, _mock_sleep):
        def handler(request):
            return httpx.Response(500, text="server error")
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with self.assertRaises(psi_client.PsiApiError):
            psi_client.run_pagespeed("https://example.com", "fake-key", max_retries=2, client=client)

    def test_raises_immediately_on_non_retryable_status(self):
        def handler(request):
            return httpx.Response(403, text="forbidden")
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with self.assertRaises(psi_client.PsiApiError):
            psi_client.run_pagespeed("https://example.com", "fake-key", max_retries=3, client=client)

    def test_raises_without_api_key(self):
        with self.assertRaises(psi_client.PsiApiError):
            psi_client.run_pagespeed("https://example.com", "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/discovery && .venv\Scripts\python -m unittest test_psi_client -v`
Expected: FAIL — `AttributeError: module 'psi_client' has no attribute 'run_pagespeed'`

- [ ] **Step 3: Write the implementation**

```python
# append to agents/discovery/psi_client.py

def run_pagespeed(url: str, api_key: str, max_retries: int = 3, client: httpx.Client | None = None) -> dict:
    """Call PSI v5 for `url` (mobile strategy, performance+seo categories).
    Returns the raw parsed JSON response -- pass it to
    parse_pagespeed_result() for the fields site_audit.py needs."""
    if not api_key:
        raise PsiApiError("PSI_API_KEY is not set")

    params = {
        "url": url,
        "key": api_key,
        "strategy": "mobile",
        "category": ["performance", "seo"],
    }

    owns_client = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        last_error = None
        for attempt in range(max_retries):
            response = client.get(PSI_URL, params=params)
            if response.status_code == 200:
                return response.json()
            if response.status_code in (429, 500, 502, 503):
                last_error = f"{response.status_code}: {response.text}"
                time.sleep(2 ** attempt)
                continue
            raise PsiApiError(f"PSI API error {response.status_code}: {response.text}")
        raise PsiApiError(f"PSI API failed after {max_retries} retries: {last_error}")
    finally:
        if owns_client:
            client.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/discovery && .venv\Scripts\python -m unittest test_psi_client -v`
Expected: PASS (8 tests total)

- [ ] **Step 5: Manually verify the real API shape once, using a real key**

This is the one point in the plan that touches the live API — do it once, by hand, before trusting the fixtures above against reality:

```bash
cd agents/discovery
.venv\Scripts\python -c "import psi_client, json; print(json.dumps(psi_client.run_pagespeed('https://example.com', 'YOUR_REAL_PSI_KEY'), indent=2))" > psi_sample_response.json
```

Open `psi_sample_response.json` and confirm `lighthouseResult.categories.performance.score`, `lighthouseResult.audits['largest-contentful-paint'].numericValue`, `lighthouseResult.audits['cumulative-layout-shift'].numericValue`, and `lighthouseResult.audits['viewport'].score` exist at the paths this code expects. If Google has changed any of these paths, fix `parse_pagespeed_result` (Task 1) before continuing — everything downstream depends on it being accurate, not assumed. Delete `psi_sample_response.json` afterward (it's a scratch file, not part of the commit — already covered by the root `.gitignore`'s `*.db`? No — add it to your local ignore or just delete it manually; it's real response data, not something to commit).

- [ ] **Step 6: Commit**

```bash
git add agents/discovery/psi_client.py agents/discovery/test_psi_client.py
git commit -m "Add PageSpeed Insights API client with retry/backoff"
```

---

### Task 3: On-page SEO and conversion signal parsers

**Files:**
- Create: `agents/discovery/site_audit.py`
- Create: `agents/discovery/test_site_audit.py`

**Interfaces:**
- Produces (all pure functions, no network):
  - `extract_title(html: str) -> str | None`
  - `extract_meta_description(html: str) -> str | None`
  - `count_h1(html: str) -> int`
  - `has_heading_hierarchy_skip(html: str) -> bool`
  - `has_self_referencing_canonical(html: str, url: str) -> bool`
  - `has_noindex_robots_meta(html: str) -> bool`
  - `has_json_ld_local_business(html: str) -> bool`
  - `extract_phone_number(html: str) -> str | None`
  - `has_contact_form_or_booking_link(html: str) -> bool`
  - `has_cta(html: str) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# agents/discovery/test_site_audit.py
import unittest

import site_audit


class OnPageSeoParserTests(unittest.TestCase):
    def test_extract_title_present(self):
        html = "<html><head><title>Old School Ink Tattoo Shop</title></head></html>"
        self.assertEqual(site_audit.extract_title(html), "Old School Ink Tattoo Shop")

    def test_extract_title_missing(self):
        self.assertIsNone(site_audit.extract_title("<html><head></head></html>"))

    def test_extract_meta_description_present(self):
        html = '<meta name="description" content="Best tattoo shop in Springfield">'
        self.assertEqual(site_audit.extract_meta_description(html), "Best tattoo shop in Springfield")

    def test_extract_meta_description_missing(self):
        self.assertIsNone(site_audit.extract_meta_description("<html></html>"))

    def test_count_h1_single(self):
        self.assertEqual(site_audit.count_h1("<h1>Welcome</h1><h2>Services</h2>"), 1)

    def test_count_h1_multiple(self):
        self.assertEqual(site_audit.count_h1("<h1>Welcome</h1><h1>Also Welcome</h1>"), 2)

    def test_count_h1_none(self):
        self.assertEqual(site_audit.count_h1("<h2>No H1 here</h2>"), 0)

    def test_heading_hierarchy_skip_detected(self):
        self.assertTrue(site_audit.has_heading_hierarchy_skip("<h1>Welcome</h1><h3>Services</h3>"))

    def test_heading_hierarchy_no_skip(self):
        html = "<h1>Welcome</h1><h2>Services</h2><h3>Tattoos</h3>"
        self.assertFalse(site_audit.has_heading_hierarchy_skip(html))

    def test_self_referencing_canonical_true(self):
        html = '<link rel="canonical" href="https://example.com/">'
        self.assertTrue(site_audit.has_self_referencing_canonical(html, "https://example.com/"))

    def test_self_referencing_canonical_false(self):
        html = '<link rel="canonical" href="https://other-domain.com/">'
        self.assertFalse(site_audit.has_self_referencing_canonical(html, "https://example.com/"))

    def test_self_referencing_canonical_missing(self):
        self.assertFalse(site_audit.has_self_referencing_canonical("<html></html>", "https://example.com/"))

    def test_noindex_detected(self):
        html = '<meta name="robots" content="noindex, nofollow">'
        self.assertTrue(site_audit.has_noindex_robots_meta(html))

    def test_noindex_absent(self):
        html = '<meta name="robots" content="index, follow">'
        self.assertFalse(site_audit.has_noindex_robots_meta(html))

    def test_json_ld_local_business_detected(self):
        html = '''<script type="application/ld+json">
        {"@context": "https://schema.org", "@type": "LocalBusiness", "name": "Old School Ink"}
        </script>'''
        self.assertTrue(site_audit.has_json_ld_local_business(html))

    def test_json_ld_absent(self):
        self.assertFalse(site_audit.has_json_ld_local_business("<html></html>"))

    def test_json_ld_malformed_does_not_crash(self):
        html = '<script type="application/ld+json">{not valid json</script>'
        self.assertFalse(site_audit.has_json_ld_local_business(html))

    def test_extract_phone_number_present(self):
        html = "<p>Call us at (217) 555-0100 today</p>"
        self.assertEqual(site_audit.extract_phone_number(html), "(217) 555-0100")

    def test_extract_phone_number_absent(self):
        self.assertIsNone(site_audit.extract_phone_number("<p>No phone here</p>"))

    def test_contact_form_detected(self):
        html = '<form action="/contact"><input type="email"></form>'
        self.assertTrue(site_audit.has_contact_form_or_booking_link(html))

    def test_contact_form_absent(self):
        self.assertFalse(site_audit.has_contact_form_or_booking_link("<html></html>"))

    def test_cta_detected(self):
        self.assertTrue(site_audit.has_cta('<a href="/book">Book Now</a>'))

    def test_cta_absent(self):
        self.assertFalse(site_audit.has_cta("<p>Welcome to our shop</p>"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/discovery && .venv\Scripts\python -m unittest test_site_audit -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'site_audit'`

- [ ] **Step 3: Write the implementation**

```python
# agents/discovery/site_audit.py
"""Website audit for qualified_outdated leads: real Core Web Vitals (via
psi_client) plus deterministic on-page SEO and conversion-signal checks.
Only runs for leads already classified qualified_outdated by
site_check.py -- see docs/superpowers/specs/2026-08-11-website-audit-agent-design.md.
"""

import datetime
import json
import re
from urllib.parse import urljoin, urlparse

import psi_client
import site_check

USER_AGENT = site_check.USER_AGENT

PHONE_RE = re.compile(r"(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}")
CTA_PHRASES = [
    "call now", "book now", "book online", "schedule",
    "contact us", "get a quote", "book an appointment",
]
CONTACT_FORM_MARKERS = ["<form", "calendly.com", "book.squareup", "acuityscheduling.com"]


def extract_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    title = re.sub(r"\s+", " ", match.group(1)).strip()
    return title or None


def extract_meta_description(html: str) -> str | None:
    match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        html, re.IGNORECASE | re.DOTALL,
    )
    if not match:
        match = re.search(
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
            html, re.IGNORECASE | re.DOTALL,
        )
    if not match:
        return None
    desc = re.sub(r"\s+", " ", match.group(1)).strip()
    return desc or None


def count_h1(html: str) -> int:
    return len(re.findall(r"<h1[\s>]", html, re.IGNORECASE))


def has_heading_hierarchy_skip(html: str) -> bool:
    levels = [int(n) for n in re.findall(r"<h([1-6])[\s>]", html, re.IGNORECASE)]
    max_seen = 0
    for level in levels:
        if max_seen and level > max_seen + 1:
            return True
        max_seen = max(max_seen, level)
    return False


def has_self_referencing_canonical(html: str, url: str) -> bool:
    match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\'](.*?)["\']', html, re.IGNORECASE)
    if not match:
        return False
    resolved = urljoin(url, match.group(1).strip())
    return _normalize_url(resolved) == _normalize_url(url)


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc.lower()}{path}"


def has_noindex_robots_meta(html: str) -> bool:
    match = re.search(r'<meta[^>]+name=["\']robots["\'][^>]+content=["\'](.*?)["\']', html, re.IGNORECASE)
    if not match:
        return False
    return "noindex" in match.group(1).lower()


def has_json_ld_local_business(html: str) -> bool:
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.IGNORECASE | re.DOTALL,
    )
    for block in blocks:
        try:
            data = json.loads(block.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        for entry in (data if isinstance(data, list) else [data]):
            if not isinstance(entry, dict):
                continue
            entry_type = entry.get("@type", "")
            types = entry_type if isinstance(entry_type, list) else [entry_type]
            if any(isinstance(t, str) and t in ("LocalBusiness", "Organization") for t in types):
                return True
    return False


def extract_phone_number(html: str) -> str | None:
    match = PHONE_RE.search(html)
    return match.group(0).strip() if match else None


def has_contact_form_or_booking_link(html: str) -> bool:
    lower_html = html.lower()
    return any(marker in lower_html for marker in CONTACT_FORM_MARKERS)


def has_cta(html: str) -> bool:
    lower_html = html.lower()
    return any(phrase in lower_html for phrase in CTA_PHRASES)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/discovery && .venv\Scripts\python -m unittest test_site_audit -v`
Expected: PASS (21 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/discovery/site_audit.py agents/discovery/test_site_audit.py
git commit -m "Add on-page SEO and conversion signal parsers"
```

---

### Task 4: Network helpers (homepage fetch + sitemap/robots existence check)

**Files:**
- Modify: `agents/discovery/site_check.py` (rename one private helper to public)
- Modify: `agents/discovery/site_audit.py`
- Modify: `agents/discovery/test_site_audit.py`

**Interfaces:**
- Consumes: nothing new from earlier tasks
- Produces:
  - `site_check.robots_allow_fetch(url: str) -> bool` (renamed from `_robots_allow_fetch` — same behavior, now importable by other modules)
  - `fetch_homepage_html(url: str, timeout: float = 10.0, client: httpx.Client | None = None) -> tuple[str | None, str | None]` — returns `(html, error)`; `html` is `None` if robots.txt disallows the fetch or the request fails, and `error` explains why
  - `check_url_exists(url: str, client: httpx.Client | None = None) -> bool`

- [ ] **Step 1: Rename the private helper in site_check.py**

In `agents/discovery/site_check.py`, rename `_robots_allow_fetch` to `robots_allow_fetch` (drop the leading underscore) at its definition (currently line 91) and at its one call site (currently line 41, `if not _robots_allow_fetch(url):`). Pure rename, no behavior change — `site_check`'s own qualification logic is untouched.

- [ ] **Step 2: Write the failing tests**

```python
# append to agents/discovery/test_site_audit.py
from unittest.mock import patch

import httpx


class FetchHomepageHtmlTests(unittest.TestCase):
    def test_returns_html_on_success(self):
        def handler(request):
            return httpx.Response(200, text="<html>hi</html>")
        client = httpx.Client(transport=httpx.MockTransport(handler))
        html, error = site_audit.fetch_homepage_html("https://example.com", client=client)
        self.assertEqual(html, "<html>hi</html>")
        self.assertIsNone(error)

    def test_returns_error_on_http_failure(self):
        def handler(request):
            raise httpx.ConnectTimeout("timed out", request=request)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        html, error = site_audit.fetch_homepage_html("https://example.com", client=client)
        self.assertIsNone(html)
        self.assertIsNotNone(error)

    @patch("site_audit.site_check.robots_allow_fetch", return_value=False)
    def test_respects_robots_disallow(self, _mock):
        html, error = site_audit.fetch_homepage_html("https://example.com")
        self.assertIsNone(html)
        self.assertEqual(error, "robots_disallowed")


class CheckUrlExistsTests(unittest.TestCase):
    def test_true_on_200(self):
        def handler(request):
            return httpx.Response(200)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.assertTrue(site_audit.check_url_exists("https://example.com/sitemap.xml", client=client))

    def test_false_on_404(self):
        def handler(request):
            return httpx.Response(404)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.assertFalse(site_audit.check_url_exists("https://example.com/sitemap.xml", client=client))

    def test_false_on_connection_error(self):
        def handler(request):
            raise httpx.ConnectError("refused", request=request)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.assertFalse(site_audit.check_url_exists("https://example.com/sitemap.xml", client=client))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd agents/discovery && .venv\Scripts\python -m unittest test_site_audit -v`
Expected: FAIL — `AttributeError: module 'site_audit' has no attribute 'fetch_homepage_html'`

- [ ] **Step 4: Write the implementation**

```python
# append to agents/discovery/site_audit.py (add `import httpx` to the top imports)

def fetch_homepage_html(url: str, timeout: float = 10.0, client: "httpx.Client | None" = None) -> tuple[str | None, str | None]:
    """Returns (html, error). html is None if robots.txt disallows the
    fetch or the request fails; error explains why when html is None."""
    if not site_check.robots_allow_fetch(url):
        return None, "robots_disallowed"

    owns_client = client is None
    client = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        response = client.get(url, headers={"User-Agent": USER_AGENT})
        return response.text, None
    except httpx.HTTPError as exc:
        return None, str(exc)
    finally:
        if owns_client:
            client.close()


def check_url_exists(url: str, client: "httpx.Client | None" = None) -> bool:
    owns_client = client is None
    client = client or httpx.Client(timeout=10.0, follow_redirects=True)
    try:
        response = client.head(url, headers={"User-Agent": USER_AGENT})
        return response.status_code == 200
    except httpx.HTTPError:
        return False
    finally:
        if owns_client:
            client.close()
```

Add `import httpx` near the top of `site_audit.py` alongside the existing `import psi_client` / `import site_check` lines.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd agents/discovery && .venv\Scripts\python -m unittest test_site_audit -v`
Expected: PASS (27 tests total)

- [ ] **Step 6: Commit**

```bash
git add agents/discovery/site_check.py agents/discovery/site_audit.py agents/discovery/test_site_audit.py
git commit -m "Add homepage fetch and sitemap/robots existence check helpers"
```

---

### Task 5: `audit_site()` orchestrator

**Files:**
- Modify: `agents/discovery/site_audit.py`
- Modify: `agents/discovery/test_site_audit.py`

**Interfaces:**
- Consumes: every function from Tasks 1–4 (`psi_client.run_pagespeed`, `psi_client.parse_pagespeed_result`, `psi_client.PsiApiError`, all the pure parsers, `fetch_homepage_html`, `check_url_exists`)
- Produces: `audit_site(url: str, psi_api_key: str) -> dict` returning `{"status": "ok"|"error"|"skipped", "score": int|None, "signals": dict, "run_at": str}`. This is the function `discovery_agent.py` calls in Task 7.

Contract: `status="skipped"` means no usable data at all (empty URL, or the homepage fetch itself failed/was disallowed) — `signals` will be empty or just `{"fetch_error": ...}`. `status="error"` means the homepage fetch succeeded and on-page/conversion signals were computed, but PSI failed — `signals` still contains the on-page/conversion findings, `score` stays `None`, and `signals["psi_error"]` explains what went wrong. `status="ok"` means everything succeeded.

- [ ] **Step 1: Write the failing tests**

```python
# append to agents/discovery/test_site_audit.py
import psi_client


class AuditSiteTests(unittest.TestCase):
    def test_skipped_when_no_url(self):
        result = site_audit.audit_site("", "fake-key")
        self.assertEqual(result["status"], "skipped")
        self.assertIsNone(result["score"])

    @patch("site_audit.fetch_homepage_html", return_value=(None, "robots_disallowed"))
    def test_skipped_when_fetch_fails(self, _mock):
        result = site_audit.audit_site("https://example.com", "fake-key")
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["signals"]["fetch_error"], "robots_disallowed")

    @patch("site_audit.psi_client.run_pagespeed", side_effect=psi_client.PsiApiError("boom"))
    @patch("site_audit.check_url_exists", return_value=True)
    @patch("site_audit.fetch_homepage_html", return_value=("<html><title>Shop</title></html>", None))
    def test_status_error_when_psi_fails_but_keeps_onpage_signals(self, _fetch, _url_exists, _psi):
        result = site_audit.audit_site("https://example.com", "fake-key")
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["score"])
        self.assertEqual(result["signals"]["title"], "Shop")
        self.assertIn("psi_error", result["signals"])

    @patch(
        "site_audit.psi_client.run_pagespeed",
        return_value={
            "lighthouseResult": {
                "categories": {"performance": {"score": 0.75}},
                "audits": {},
            }
        },
    )
    @patch("site_audit.check_url_exists", return_value=True)
    @patch("site_audit.fetch_homepage_html", return_value=("<html><title>Shop</title></html>", None))
    def test_status_ok_full_flow(self, _fetch, _url_exists, _psi):
        result = site_audit.audit_site("https://example.com", "fake-key")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["score"], 75)
        self.assertTrue(result["signals"]["sitemap_exists"])
        self.assertTrue(result["signals"]["robots_txt_exists"])
        self.assertEqual(result["signals"]["title"], "Shop")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/discovery && .venv\Scripts\python -m unittest test_site_audit -v`
Expected: FAIL — `AttributeError: module 'site_audit' has no attribute 'audit_site'`

- [ ] **Step 3: Write the implementation**

```python
# append to agents/discovery/site_audit.py

def audit_site(url: str, psi_api_key: str) -> dict:
    run_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if not url:
        return {"status": "skipped", "score": None, "signals": {}, "run_at": run_at}

    html, fetch_error = fetch_homepage_html(url)
    if html is None:
        return {"status": "skipped", "score": None, "signals": {"fetch_error": fetch_error}, "run_at": run_at}

    signals: dict = {
        "title": extract_title(html),
        "meta_description": extract_meta_description(html),
        "h1_count": count_h1(html),
        "heading_hierarchy_skip": has_heading_hierarchy_skip(html),
        "self_referencing_canonical": has_self_referencing_canonical(html, url),
        "noindex": has_noindex_robots_meta(html),
        "json_ld_local_business": has_json_ld_local_business(html),
        "phone_number": extract_phone_number(html),
        "contact_form_or_booking_link": has_contact_form_or_booking_link(html),
        "cta_present": has_cta(html),
    }

    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    signals["sitemap_exists"] = check_url_exists(urljoin(origin, "/sitemap.xml"))
    signals["robots_txt_exists"] = check_url_exists(urljoin(origin, "/robots.txt"))

    try:
        raw_psi = psi_client.run_pagespeed(url, psi_api_key)
        psi_signals = psi_client.parse_pagespeed_result(raw_psi)
        signals.update(psi_signals)
        return {"status": "ok", "score": psi_signals["performance_score"], "signals": signals, "run_at": run_at}
    except psi_client.PsiApiError as exc:
        signals["psi_error"] = str(exc)
        return {"status": "error", "score": None, "signals": signals, "run_at": run_at}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/discovery && .venv\Scripts\python -m unittest test_site_audit -v`
Expected: PASS (31 tests total)

- [ ] **Step 5: Commit**

```bash
git add agents/discovery/site_audit.py agents/discovery/test_site_audit.py
git commit -m "Add audit_site orchestrator"
```

---

### Task 6: Schema migration and `update_lead_audit`

**Files:**
- Modify: `agents/discovery/schema.sql`
- Modify: `agents/discovery/db.py`
- Create: `agents/discovery/test_db_migration.py`

**Interfaces:**
- Produces:
  - `db._migrate_audit_columns(conn: sqlite3.Connection) -> None` (called automatically from `db.init_db`)
  - `db.update_lead_audit(conn: sqlite3.Connection, google_place_id: str, audit_status: str, audit_score: int | None, audit_signals: dict, audit_run_at: str) -> None` — this is what `discovery_agent.py` calls in Task 7

This is the highest-risk task in the plan: `agents/discovery/leads.db` already has 10 real leads that Outreach and Dossier depend on. The migration must be additive and idempotent — safe to run against that real file, and safe to run twice (since `init_db()` runs on every single invocation of `discovery_agent.py`).

- [ ] **Step 1: Write the failing tests**

```python
# agents/discovery/test_db_migration.py
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import db

# Exact copy of schema.sql as it exists before this task's changes -- used
# to simulate the real, already-populated leads.db before migration.
PRE_MIGRATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_cells (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    label         TEXT UNIQUE NOT NULL,
    state         TEXT NOT NULL,
    lat           REAL NOT NULL,
    lng           REAL NOT NULL,
    radius_m      INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    result_count  INTEGER,
    run_at        TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS leads (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    google_place_id     TEXT UNIQUE NOT NULL,
    business_name       TEXT NOT NULL,
    formatted_address    TEXT,
    city                TEXT,
    state               TEXT,
    zip                 TEXT,
    phone               TEXT,
    website_url         TEXT,
    has_website         INTEGER NOT NULL DEFAULT 0,
    website_status      TEXT NOT NULL DEFAULT 'unknown',
    website_signals     TEXT,
    qualification_status TEXT NOT NULL DEFAULT 'needs_review',
    discovery_source    TEXT NOT NULL DEFAULT 'google_places',
    search_cell         TEXT,
    discovered_at       TEXT NOT NULL,
    raw_places_json     TEXT
);

CREATE INDEX IF NOT EXISTS idx_leads_qualification ON leads (qualification_status);
CREATE INDEX IF NOT EXISTS idx_leads_state ON leads (state);
"""


class MigrationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db_path = tmp.name

    def tearDown(self):
        Path(self.db_path).unlink(missing_ok=True)

    def test_migration_adds_columns_and_preserves_existing_rows(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(PRE_MIGRATION_SCHEMA)
        conn.execute(
            "INSERT INTO leads (google_place_id, business_name, qualification_status, discovered_at) "
            "VALUES (?, ?, ?, ?)",
            ("place-1", "Old School Ink", "qualified_outdated", "2026-01-01T00:00:00Z"),
        )
        conn.commit()
        conn.close()

        db.init_db(self.db_path)

        conn = db.get_connection(self.db_path)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(leads)").fetchall()}
        for expected in ("audit_status", "audit_score", "audit_signals", "audit_run_at"):
            self.assertIn(expected, columns)

        row = conn.execute("SELECT * FROM leads WHERE google_place_id = ?", ("place-1",)).fetchone()
        self.assertEqual(row["business_name"], "Old School Ink")
        self.assertEqual(row["audit_status"], "not_run")
        conn.close()

    def test_running_init_db_twice_is_safe(self):
        db.init_db(self.db_path)
        db.init_db(self.db_path)  # must not raise "duplicate column name"
        conn = db.get_connection(self.db_path)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(leads)").fetchall()}
        self.assertIn("audit_status", columns)
        conn.close()

    def test_update_lead_audit_writes_fields(self):
        db.init_db(self.db_path)
        conn = db.get_connection(self.db_path)
        conn.execute(
            "INSERT INTO leads (google_place_id, business_name, discovered_at) VALUES (?, ?, ?)",
            ("place-2", "Test Shop", "2026-01-01T00:00:00Z"),
        )
        conn.commit()

        db.update_lead_audit(conn, "place-2", "ok", 42, {"title": "Test"}, "2026-01-02T00:00:00Z")

        row = conn.execute("SELECT * FROM leads WHERE google_place_id = ?", ("place-2",)).fetchone()
        self.assertEqual(row["audit_status"], "ok")
        self.assertEqual(row["audit_score"], 42)
        self.assertEqual(json.loads(row["audit_signals"]), {"title": "Test"})
        self.assertEqual(row["audit_run_at"], "2026-01-02T00:00:00Z")
        conn.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/discovery && .venv\Scripts\python -m unittest test_db_migration -v`
Expected: FAIL — `AssertionError` (columns don't exist yet) or `AttributeError: module 'db' has no attribute 'update_lead_audit'`

- [ ] **Step 3: Update schema.sql**

In `agents/discovery/schema.sql`, change the `leads` table's last column line from:

```sql
    raw_places_json     TEXT
);
```

to:

```sql
    raw_places_json     TEXT,
    audit_status        TEXT NOT NULL DEFAULT 'not_run',
    audit_score         INTEGER,
    audit_signals       TEXT,
    audit_run_at        TEXT
);
```

This covers fresh databases. `db.py`'s migration (next step) covers the existing populated one.

- [ ] **Step 4: Add the migration and `update_lead_audit` to db.py**

```python
# add near the top of agents/discovery/db.py, after SCHEMA_PATH

AUDIT_COLUMNS = {
    "audit_status": "TEXT NOT NULL DEFAULT 'not_run'",
    "audit_score": "INTEGER",
    "audit_signals": "TEXT",
    "audit_run_at": "TEXT",
}


def _migrate_audit_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(leads)").fetchall()}
    for column, definition in AUDIT_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {column} {definition}")
    conn.commit()
```

Modify the existing `init_db` function to call it:

```python
def init_db(db_path: str) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
        _migrate_audit_columns(conn)
    finally:
        conn.close()
```

Add the new update function at the end of `db.py`:

```python
def update_lead_audit(
    conn: sqlite3.Connection,
    google_place_id: str,
    audit_status: str,
    audit_score: int | None,
    audit_signals: dict,
    audit_run_at: str,
) -> None:
    conn.execute(
        """
        UPDATE leads
        SET audit_status = ?, audit_score = ?, audit_signals = ?, audit_run_at = ?
        WHERE google_place_id = ?
        """,
        (audit_status, audit_score, json.dumps(audit_signals or {}), audit_run_at, google_place_id),
    )
    conn.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd agents/discovery && .venv\Scripts\python -m unittest test_db_migration -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Verify against the real leads.db before moving on**

```bash
cd agents/discovery
copy leads.db leads.db.backup
.venv\Scripts\python -c "import db; db.init_db('leads.db')"
.venv\Scripts\python -c "import sqlite3; c = sqlite3.connect('leads.db'); print([r[1] for r in c.execute('PRAGMA table_info(leads)')]); print(c.execute('SELECT COUNT(*) FROM leads').fetchone())"
```

Confirm the printed column list includes `audit_status`, `audit_score`, `audit_signals`, `audit_run_at`, and the row count matches what it was before (10, per ARCHITECTURE.md). Delete `leads.db.backup` once confirmed; keep it if anything looks wrong and investigate before proceeding.

- [ ] **Step 7: Commit**

```bash
git add agents/discovery/schema.sql agents/discovery/db.py agents/discovery/test_db_migration.py
git commit -m "Add audit columns migration and update_lead_audit"
```

---

### Task 7: Wire into discovery_agent.py, config, and docs

**Files:**
- Modify: `agents/discovery/discovery_agent.py`
- Modify: `agents/discovery/.env.example`
- Modify: `agents/discovery/README.md`

**Interfaces:**
- Consumes: `site_audit.audit_site` (Task 5), `db.update_lead_audit` (Task 6)

This task is orchestration wiring, not new pure logic — following this project's existing convention (every other agent's top-level `run()` loop is verified via `--dry-run` plus a real smoke test and manual spot-check, not unit tests; see ARCHITECTURE.md §8, §12), it's verified that way rather than with `unittest`.

- [ ] **Step 1: Add the PSI key and import**

In `agents/discovery/discovery_agent.py`, add near the other imports:

```python
import site_audit
```

In `run()`, add alongside the existing `api_key` line:

```python
def run(db_path: str, limit_cities: int | None, dry_run: bool, state_filter: str | None) -> None:
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    psi_api_key = os.environ.get("PSI_API_KEY", "")
```

- [ ] **Step 2: Call the audit after each lead is written**

In the `for place in places:` loop inside `run()`, after the existing `print(f"  [{lead['qualification_status']}] {lead['business_name']}")` line, add:

```python
            if not dry_run and lead["qualification_status"] == "qualified_outdated":
                audit_result = site_audit.audit_site(lead["website_url"], psi_api_key)
                db.update_lead_audit(
                    conn,
                    lead["google_place_id"],
                    audit_result["status"],
                    audit_result["score"],
                    audit_result["signals"],
                    audit_result["run_at"],
                )
                print(f"    audit: {audit_result['status']} (score={audit_result['score']})")
```

The `not dry_run` guard is deliberate: `discovery_agent.py`'s own docstring promises `--dry-run` means "no API calls" — PSI must never fire during a dry run, regardless of what the fake data's qualification status happens to be.

- [ ] **Step 3: Update .env.example**

```
# agents/discovery/.env.example
GOOGLE_PLACES_API_KEY=
PSI_API_KEY=
```

- [ ] **Step 4: Update README.md**

Add a new section to `agents/discovery/README.md`, after the existing "## How qualification works" section:

```markdown
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
```

- [ ] **Step 5: Manual verification against a real existing lead**

Nested-quote one-liners are fragile and shell-dependent (PowerShell and Git Bash escape `"` differently) — use small scratch scripts instead, deleted after use.

```python
# agents/discovery/_scratch_find_outdated_lead.py
import sqlite3

conn = sqlite3.connect("leads.db")
row = conn.execute(
    "SELECT business_name, website_url FROM leads WHERE qualification_status = ? LIMIT 1",
    ("qualified_outdated",),
).fetchone()
print(row)
```

```bash
cd agents/discovery
.venv\Scripts\python _scratch_find_outdated_lead.py
```

Take the printed `website_url` and run the audit directly:

```python
# agents/discovery/_scratch_run_audit.py
import json
import os

from dotenv import load_dotenv

import site_audit

load_dotenv()
result = site_audit.audit_site("PASTE_URL_HERE", os.environ["PSI_API_KEY"])
print(json.dumps(result, indent=2))
```

```bash
.venv\Scripts\python _scratch_run_audit.py
```

Confirm `status` is `ok` or a sensible `error`, and spot-check a few fields (title, phone number, CTA presence) against actually opening that site in a browser — don't just trust that the script exited without an exception. Delete both scratch scripts once done (they're throwaway, not part of the commit).

- [ ] **Step 6: Real smoke test through the full pipeline**

```bash
.venv\Scripts\python discovery_agent.py --limit-cities 1
```

Confirm the new `audit: ...` print line appears for any `qualified_outdated` lead found in that city, then confirm it landed in the database:

```python
# agents/discovery/_scratch_check_audit_rows.py
import sqlite3

conn = sqlite3.connect("leads.db")
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT business_name, audit_status, audit_score FROM leads WHERE audit_status != ?",
    ("not_run",),
).fetchall()
for row in rows:
    print(dict(row))
```

```bash
.venv\Scripts\python _scratch_check_audit_rows.py
```

Delete this scratch script once done.

- [ ] **Step 7: Commit**

```bash
git add agents/discovery/discovery_agent.py agents/discovery/.env.example agents/discovery/README.md
git commit -m "Wire website audit into Discovery's per-lead pipeline"
```

---

## Explicitly not in this plan

- Feeding `audit_signals` into Dossier's prompt so it actually appears in generated pitches — small, mechanical follow-up once this lands (spec §10)
- The weighted 0–100 prospect score — separate spec/plan (spec §2, §10)
