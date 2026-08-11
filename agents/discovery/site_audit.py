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
