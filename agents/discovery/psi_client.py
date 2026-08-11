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
    viewport_audit = audits.get("viewport-insight", {})

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
            try:
                response = client.get(PSI_URL, params=params)
            except httpx.HTTPError as exc:
                raise PsiApiError(f"PSI API request failed: {exc}") from exc
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
