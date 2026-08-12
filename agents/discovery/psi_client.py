"""Thin wrapper around Google's PageSpeed Insights v5 API (runPagespeed).

Free, quota-limited (not billed) -- see
https://developers.google.com/speed/docs/insights/v5/get-started.
Retry/backoff and JSON-parsing safety are shared with places_client.py
via http_retry.py, not reimplemented here.
"""

import httpx

import http_retry

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
        response = http_retry.request_with_retry(
            lambda: client.get(PSI_URL, params=params), PsiApiError, "PSI API", max_retries=max_retries,
        )
        return http_retry.parse_json_response(response, PsiApiError, "PSI API")
    finally:
        if owns_client:
            client.close()
