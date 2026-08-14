"""Sales Handoff Dossier Agent.

Compiles everything a human needs the moment a lead expresses interest:
lead history, a research summary (via Claude's web_search tool -- no
scraping), the demo site status, communication history, recommended
talking points, and rough estimates for budget and likelihood of closing.

This is the "Human Sales Step" from the original project brief -- the
point where the AI system hands off to a person. It does not contact
leads, qualify interest, or make any decisions; it only assembles context
for a human who is about to have a conversation.

Also pulls real aggregate performance data from ../scheduler, ../reply_triage,
and ../outcomes (sent/replied/closed counts, real won-deal values) and feeds
it into the likelihood/budget estimate when any exists -- see
../outcomes/README.md. Until real outreach has actually happened, there's
nothing to pull, and this section is simply omitted rather than faked.

This is the most expensive call in the pipeline (tokens + a web_search
call per lead) -- prefer --business for everyday use over generating for
the whole batch. See ../../ARCHITECTURE.md's cost-effectiveness notes.

Usage:
    python generate_dossier.py --business "Village Tattoo NYC"  # recommended everyday usage
    python generate_dossier.py --limit 3      # smoke test on first 3
    python generate_dossier.py                # every qualified lead -- costs add up, use deliberately
    python generate_dossier.py --force         # regenerate existing dossiers
"""

import argparse
import importlib.util
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).parent.parent
outcome_stats = _load_module("outcome_stats_module", ROOT / "outcomes" / "stats.py")

MODEL = "claude-sonnet-5"
DEFAULT_DB = Path(__file__).parent.parent / "discovery" / "leads.db"
DEFAULT_DEMO_DIR = Path(__file__).parent.parent / "website_demo" / "output"
DEFAULT_DRAFTS_DIR = Path(__file__).parent.parent / "outreach" / "drafts"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "dossiers"
DEFAULT_SENDS_DB = ROOT / "scheduler" / "sends.db"
DEFAULT_REPLIES_DB = ROOT / "reply_triage" / "replies.db"
DEFAULT_OUTCOMES_DB = ROOT / "outcomes" / "outcomes.db"
QUALIFYING_STATUSES = ("qualified_no_website", "qualified_outdated")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SYSTEM_PROMPT = """You prepare a handoff brief for a human salesperson about to \
talk to a specific tattoo shop lead for a web-design business.

You will be given real facts about the shop (from Google's business \
listing) and told whether a demo site and outreach draft already exist. \
You have a web_search tool -- use it to find a *little* public context \
(reviews, social presence, anything notable) if it's genuinely findable; \
if search turns up nothing useful, say so plainly rather than padding the \
summary with generic filler.

Do not fabricate anything -- no invented reviews, no invented owner names, \
no invented specialties. If you don't know something, say you don't know.

For the budget estimate and likelihood of closing: these are rough, \
non-authoritative estimates meant to help a salesperson prioritize their \
time, not a promise of accuracy. Do not give a fake-precise number (e.g. a \
made-up percentage). Use a plain qualitative judgment (low/medium/high) and \
explain the actual signals behind it -- shop appears to be a single \
location vs a chain, review count/density if found, how badly they need a \
web presence, etc. If the signals are thin, say the confidence is low \
rather than picking an arbitrary level.

You may be given real aggregate performance data from this business's \
actual past outreach (leads contacted, replies, closed deals so far). If \
it's provided, factor it into your likelihood/budget reasoning -- but if \
the sample size is small, say so explicitly and don't treat a handful of \
data points as a reliable rate. A stated small sample is more honest and \
more useful to the salesperson than a confident-sounding number with \
nothing real behind it.

You may also be given automated site audit findings -- real checks run \
against the shop's actual existing homepage (PageSpeed/Core Web Vitals, \
missing schema markup, no phone number found on the page, etc.), not \
guesses. When present, cite them concretely in your talking points instead \
of generic phrasing like "your website looks outdated" -- a specific, \
real finding is more credible to a salesperson on a call than a vague \
claim."""


WEB_SEARCH_TOOL = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 3,  # cost cap -- this agent needs a little public context, not exhaustive research
}


DOSSIER_SCHEMA = {
    "type": "object",
    "properties": {
        "research_summary": {
            "type": "string",
            "description": "A few sentences on what public research turned up, or a plain statement that nothing notable was found.",
        },
        "talking_points": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-5 concrete, specific talking points for the salesperson's first conversation.",
        },
        "estimated_budget_range": {
            "type": "string",
            "description": "A rough qualitative budget range in words, clearly framed as an estimate.",
        },
        "budget_reasoning": {"type": "string"},
        "likelihood_of_closing": {"type": "string", "enum": ["low", "medium", "high"]},
        "likelihood_reasoning": {"type": "string"},
    },
    "required": [
        "research_summary",
        "talking_points",
        "estimated_budget_range",
        "budget_reasoning",
        "likelihood_of_closing",
        "likelihood_reasoning",
    ],
    "additionalProperties": False,
}


def fetch_qualified_leads(db_path: Path, limit: int | None, business: str | None) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" for _ in QUALIFYING_STATUSES)

    if business:
        # Targeted single-lead run -- the intended everyday usage, so a Dossier
        # only ever gets generated for the one lead actually about to be
        # contacted, not the whole backlog. Still requires the lead to be
        # currently qualified (not disqualified/suppressed-adjacent).
        query = f"SELECT * FROM leads WHERE qualification_status IN ({placeholders}) AND LOWER(business_name) = LOWER(?)"
        rows = conn.execute(query, QUALIFYING_STATUSES + (business,)).fetchall()
        conn.close()
        if not rows:
            raise SystemExit(f"No currently-qualified lead found matching business name {business!r} -- check spelling, or it may no longer be qualified")
        return rows

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


def demo_url_for(business_name: str, city: str, demo_dir: Path, site_base_url: str | None) -> str | None:
    """Real, live URL for a lead's demo, or None if it isn't actually live.
    Both conditions must hold: the demo was generated locally (demo_dir/<slug>
    exists) AND hosting is configured (site_base_url set) -- folder-exists
    alone isn't enough, since a demo can be generated without ever being
    deployed. See agents/website_demo/deploy.py for the actual hosting step."""
    if not site_base_url:
        return None
    slug = slugify(business_name, city)
    if not (demo_dir / slug).exists():
        return None
    return f"{site_base_url.rstrip('/')}/{slug}/"


def demo_status_line(demo_exists: bool, demo_url: str | None) -> str:
    """Demo site status: three real states, not a bool -- see demo_url_for()."""
    if demo_url:
        return f"a concept demo is live at {demo_url}"
    if demo_exists:
        return "a concept demo has been built (not yet hosted/live)"
    return "no demo built yet"


def build_funnel_context(funnel: dict) -> str:
    if funnel["total_sent"] == 0:
        return ""  # nothing has gone out yet -- don't manufacture a section about it

    lines = [
        "\nAggregate performance across all outreach sent so far (real data, not this lead specifically):",
        f"- {funnel['total_sent']} lead(s) contacted, {funnel['total_replied']} replied",
    ]
    if funnel["reply_breakdown"]:
        breakdown = ", ".join(f"{k}: {v}" for k, v in sorted(funnel["reply_breakdown"].items()))
        lines.append(f"- Reply breakdown: {breakdown}")
    lines.append(f"- {funnel['total_outcomes_recorded']} outcome(s) recorded, {funnel['won_count']} won")
    if funnel["avg_won_value"] is not None:
        lines.append(f"- Average won deal value: ${funnel['avg_won_value']:.2f}")
    if not funnel["outcome_sample_meaningful"]:
        lines.append("- NOTE: this sample is too small to be statistically meaningful -- treat as directional context only, not a rate.")
    return "\n".join(lines)


def format_audit_findings(lead: sqlite3.Row) -> str:
    """Turn site_audit.py's stored findings (leads.audit_status/audit_signals)
    into plain-language lines the prompt can cite specifically, instead of
    the dossier having only "it's outdated" to go on. Only populated for
    qualified_outdated leads -- see discovery_agent.py. Pure function, no
    network or DB access.

    audit_status defaults to the string 'not_run' (schema.sql), not NULL --
    a lead that was never audited must be excluded explicitly, not just
    falsy-checked, or a never-run audit prints stale "nothing found" text
    as if it were a real finding."""
    status = lead["audit_status"] if "audit_status" in lead.keys() else None
    if status not in ("ok", "skipped", "error"):
        return ""

    signals = json.loads(lead["audit_signals"] or "{}")

    if status == "skipped":
        return f"\nSite audit could not run: {signals.get('fetch_error', 'unknown reason')}."

    findings = []
    if signals.get("performance_score") is not None:
        findings.append(f"mobile PageSpeed performance score {signals['performance_score']}/100")
    if signals.get("field_lcp_category"):
        findings.append(f"real-user Largest Contentful Paint: {signals['field_lcp_category'].lower()}")
    if signals.get("field_inp_category"):
        findings.append(f"real-user responsiveness (INP): {signals['field_inp_category'].lower()}")
    if not signals.get("meta_description"):
        findings.append("no meta description")
    if not signals.get("json_ld_local_business"):
        findings.append("no structured data (schema.org LocalBusiness) markup")
    if not signals.get("phone_number"):
        findings.append("no phone number found on the page")
    if not signals.get("contact_form_or_booking_link"):
        findings.append("no contact form or booking link found")
    if not signals.get("cta_present"):
        findings.append("no clear call-to-action found")
    if not signals.get("sitemap_exists"):
        findings.append("no sitemap.xml")
    if signals.get("noindex"):
        findings.append("page is marked noindex (blocked from search engines)")
    if signals.get("heading_hierarchy_skip"):
        findings.append("heading hierarchy skips levels (accessibility/SEO issue)")
    if signals.get("psi_error"):
        findings.append(f"PageSpeed check failed ({signals['psi_error']}) -- only on-page findings available")

    if not findings:
        return ""

    return "\nSite audit findings (real, automated checks against their actual homepage): " + "; ".join(findings) + "."


def build_user_prompt(lead: sqlite3.Row, demo_exists: bool, draft_exists: bool, funnel: dict) -> str:
    qualification = lead["qualification_status"]
    if qualification == "qualified_no_website":
        situation = "No website listed on Google."
    else:
        situation = f"Has a website ({lead['website_url']}) but it's outdated.{format_audit_findings(lead)}"

    return f"""Shop name: {lead['business_name']}
City/State: {lead['city']}, {lead['state']}
Phone (public, from Google listing): {lead['phone']}
Address: {lead['formatted_address']}
Situation: {situation}
Demo site status: {"a concept demo has been built (not yet hosted/live)" if demo_exists else "no demo built yet"}
Outreach status: {"a draft outreach email/SMS exists but nothing has been sent" if draft_exists else "no outreach drafted yet"}
{build_funnel_context(funnel)}

Search for public context on this shop if you can find anything real, then prepare the handoff brief."""


def query_claude(client: Anthropic, lead: sqlite3.Row, demo_exists: bool, draft_exists: bool, funnel: dict) -> dict:
    messages = [{"role": "user", "content": build_user_prompt(lead, demo_exists, draft_exists, funnel)}]

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[WEB_SEARCH_TOOL],
        output_config={"format": {"type": "json_schema", "schema": DOSSIER_SCHEMA}},
        messages=messages,
    )

    if response.stop_reason == "pause_turn":
        messages.append({"role": "assistant", "content": response.content})
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=[WEB_SEARCH_TOOL],
            output_config={"format": {"type": "json_schema", "schema": DOSSIER_SCHEMA}},
            messages=messages,
        )

    text_blocks = [b.text for b in response.content if b.type == "text"]
    return json.loads(text_blocks[-1])


def render_markdown(lead: sqlite3.Row, dossier: dict, demo_path: Path | None, draft_path: Path | None) -> str:
    lines = [
        f"# Sales Handoff Dossier: {lead['business_name']}",
        "",
        "**For internal use by the human salesperson only.** Estimates below are rough, not authoritative.",
        "",
        "## Lead History",
        "",
        f"- **Business:** {lead['business_name']}",
        f"- **Address:** {lead['formatted_address']}",
        f"- **City/State:** {lead['city']}, {lead['state']}",
        f"- **Phone:** {lead['phone']}",
        f"- **Discovered:** {lead['discovered_at']} (via {lead['discovery_source']}, search cell: {lead['search_cell']})",
        f"- **Qualification:** {lead['qualification_status']}"
        + (f" -- existing site: {lead['website_url']}" if lead["website_url"] else ""),
        "",
        "## Research Summary",
        "",
        dossier["research_summary"],
        "",
        "## Website Demo",
        "",
        f"Demo exists locally at `{demo_path}`." if demo_path else "No demo has been generated for this lead yet.",
        "This is a concept/mockup, not a hosted live site -- see the website_demo agent's README before referencing it as more than that.",
        "",
        "## Communication History",
        "",
        f"Outreach draft exists at `{draft_path}` -- status: **drafted, not reviewed, not sent**." if draft_path else "No outreach has been drafted for this lead yet.",
        "",
        "## Recommended Talking Points",
        "",
    ]
    for point in dossier["talking_points"]:
        lines.append(f"- {point}")
    lines += [
        "",
        "## Estimated Budget",
        "",
        f"**Range:** {dossier['estimated_budget_range']}",
        "",
        dossier["budget_reasoning"],
        "",
        "## Likelihood of Closing",
        "",
        f"**Assessment:** {dossier['likelihood_of_closing'].upper()}",
        "",
        dossier["likelihood_reasoning"],
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Sales Handoff Dossier Agent")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--demo-dir", type=Path, default=DEFAULT_DEMO_DIR)
    parser.add_argument("--drafts-dir", type=Path, default=DEFAULT_DRAFTS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--sends-db", type=Path, default=DEFAULT_SENDS_DB)
    parser.add_argument("--replies-db", type=Path, default=DEFAULT_REPLIES_DB)
    parser.add_argument("--outcomes-db", type=Path, default=DEFAULT_OUTCOMES_DB)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--business", default=None, help="Generate for exactly this one lead (exact business name) instead of the whole batch -- the recommended everyday usage, since this is the most expensive call in the pipeline")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"leads.db not found at {args.db} -- run the Discovery Agent first")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY not set -- add it to .env")

    client = Anthropic(api_key=api_key)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    funnel = outcome_stats.compute_funnel(args.sends_db, args.replies_db, args.outcomes_db)

    leads = fetch_qualified_leads(args.db, args.limit, args.business)
    print(f"{len(leads)} qualified lead(s) found")
    if funnel["total_sent"] > 0:
        print(f"(using real aggregate performance data: {funnel['total_sent']} sent, {funnel['total_replied']} replied, {funnel['total_outcomes_recorded']} outcomes recorded)")

    generated, skipped = 0, 0
    for lead in leads:
        slug = slugify(lead["business_name"], lead["city"] or "")
        dest = args.output_dir / slug / "dossier.md"

        if dest.exists() and not args.force:
            skipped += 1
            print(f"  {lead['business_name']} -> {dest} (already existed, skipped)")
            continue

        demo_path = args.demo_dir / slug
        demo_path = demo_path if demo_path.exists() else None
        draft_path = args.drafts_dir / slug / "draft.md"
        draft_path = draft_path if draft_path.exists() else None

        dossier = query_claude(client, lead, demo_path is not None, draft_path is not None, funnel)

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render_markdown(lead, dossier, demo_path, draft_path), encoding="utf-8")

        generated += 1
        print(f"  {lead['business_name']} -> {dest} [{dossier['likelihood_of_closing']}]")

    print(f"\nDone. {generated} generated, {skipped} skipped (already existed), output in {args.output_dir}")


if __name__ == "__main__":
    main()
