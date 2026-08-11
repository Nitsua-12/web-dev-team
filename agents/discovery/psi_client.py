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
