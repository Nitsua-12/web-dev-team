"""Cheap heuristic scoring for whether an existing business website looks outdated.

Only runs for leads that already have a website_url (Places API told us they
have no site at all -> that's handled separately, before this ever gets called).

Checks robots.txt first and skips the fetch if disallowed -- this only reads
a public page to compute a heuristic score, it never scrapes site content.
"""

import datetime
import re
import urllib.robotparser
from urllib.parse import urlparse

import httpx

USER_AGENT = "DiscoveryAgent/0.1 (+lead qualification research)"
STALE_YEAR_THRESHOLD = 3  # copyright year older than (current year - N) counts as stale
OUTDATED_SCORE_THRESHOLD = 2

BUILDER_SPLASH_MARKERS = [
    "this site is under construction",
    "godaddy website builder",
    "this domain is for sale",
    "coming soon",
    "default web site page",
]

STALE_TECH_MARKERS = [
    "<marquee",
    "<blink",
    "<object",  # commonly wraps legacy Flash embeds
    "best viewed in internet explorer",
    "best viewed with internet explorer",
]


def check_website(url: str) -> dict:
    signals: dict = {}

    if not robots_allow_fetch(url):
        signals["robots_disallowed"] = True
        return {"status": "unknown", "score": 0, "signals": signals}

    try:
        response = httpx.get(
            url, timeout=10.0, follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
    except httpx.HTTPError as exc:
        return {"status": "error", "score": 0, "signals": {"fetch_error": str(exc)}}

    if response.status_code >= 400:
        # A bot-block/error page (403/404/500/etc.) is not the site's real
        # content -- scoring it would judge the lead off a challenge page,
        # not the actual business site. "unknown" matches how a
        # robots.txt-disallowed fetch is already treated: not a verdict,
        # a signal that a human should look at this one.
        signals["fetch_error"] = f"http_{response.status_code}"
        return {"status": "unknown", "score": 0, "signals": signals}

    html = response.text
    final_url = str(response.url)

    score = 0

    not_https = not final_url.startswith("https://")
    signals["not_https"] = not_https
    score += 1 if not_https else 0

    has_viewport = bool(re.search(r'<meta[^>]+name=["\']viewport["\']', html, re.IGNORECASE))
    signals["missing_viewport_meta"] = not has_viewport
    score += 1 if not has_viewport else 0

    stale_year = _find_stale_copyright_year(html)
    signals["stale_copyright_year"] = stale_year
    score += 1 if stale_year else 0

    lower_html = html.lower()
    splash_hit = next((m for m in BUILDER_SPLASH_MARKERS if m in lower_html), None)
    signals["builder_splash_marker"] = splash_hit
    score += 1 if splash_hit else 0

    tech_hit = next((m for m in STALE_TECH_MARKERS if m in lower_html), None)
    signals["stale_tech_marker"] = tech_hit
    score += 1 if tech_hit else 0

    status = "outdated" if score >= OUTDATED_SCORE_THRESHOLD else "modern"
    return {"status": status, "score": score, "signals": signals}


def qualification_for_status(website_status: str) -> str:
    """Maps a check_website() status ('outdated'/'modern'/'unknown'/'error')
    to a qualification_status. Shared by discovery_agent.py (initial
    discovery) and reverify.py (re-checking an existing lead) so a lead
    lands in the same bucket regardless of which one classifies it -- one
    implementation, not two that could quietly drift apart. Does not
    handle the "no website at all" -> qualified_no_website case, since
    that's a precondition callers check before ever calling
    check_website() in the first place, not a status this function ever
    sees."""
    if website_status == "outdated":
        return "qualified_outdated"
    if website_status == "modern":
        return "disqualified_modern"
    return "needs_review"


def _find_stale_copyright_year(html: str) -> int | None:
    matches = re.findall(r"(?:©|copyright)\s*(\d{4})", html, re.IGNORECASE)
    if not matches:
        return None
    year = min(int(y) for y in matches)
    current_year = datetime.date.today().year
    return year if (current_year - year) >= STALE_YEAR_THRESHOLD else None


def robots_allow_fetch(url: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
    except Exception:
        return True  # no reachable robots.txt -> default to allow
    return parser.can_fetch(USER_AGENT, url)
