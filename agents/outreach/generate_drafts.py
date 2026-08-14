"""Outreach Copywriting Agent.

Drafts personalized outreach copy (email, SMS, two follow-ups) per qualified
lead using Claude. This agent ONLY drafts -- it has no send capability at
all, by design. Output goes to drafts/<slug>/ as plain markdown for a human
to review, edit, and approve before anything is ever sent through a
separate (not-yet-built) sending tool.

See README.md before using any of this for real outreach -- there are real
CAN-SPAM (email) and TCPA (SMS) legal considerations that this agent does
not resolve on its own.

Checks ../suppression/suppression.db before drafting anything for a lead --
a lead whose phone number is on the suppression list is skipped entirely
(no draft written, no API call made).

Writes draft.json alongside draft.md in each lead's folder -- the same
data, structured, for tools like ../scheduler that need to read the
follow-up day_offsets without parsing markdown.

Usage:
    python generate_drafts.py --limit 3      # smoke test on first 3
    python generate_drafts.py                # every qualified lead
    python generate_drafts.py --force         # regenerate existing drafts
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

# suppression/db.py is pure stdlib (no pip deps) -- import directly rather
# than duplicating the suppression-check logic here. See agents/suppression/README.md
sys.path.insert(0, str(Path(__file__).parent.parent / "suppression"))
import db as suppression_db

MODEL = "claude-sonnet-5"
DEFAULT_DB = Path(__file__).parent.parent / "discovery" / "leads.db"
DEFAULT_SUPPRESSION_DB = Path(__file__).parent.parent / "suppression" / "suppression.db"
DEFAULT_DEMO_DIR = Path(__file__).parent.parent / "website_demo" / "output"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "drafts"
QUALIFYING_STATUSES = ("qualified_no_website", "qualified_outdated")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SYSTEM_PROMPT = """You write cold outreach copy for a small web-design business \
that builds modern websites for local tattoo shops that currently have no \
website or an outdated one.

You will be given real facts about one specific shop (from Google's business \
listing). Use only those facts. Never invent details about the shop -- its \
staff, history, specialties, or reputation -- since none of that data was \
provided.

The pitch: a modern website concept has already been put together for this \
specific shop, and the message invites them to take a look. Do NOT claim the \
site is live or already fully built with their real photos/content -- it's a \
concept/demo, and overclaiming here is a real problem, not a nitpick. Frame \
it as "here's what we put together for you" / "want to see it" rather than \
"your new site is ready."

When you're told a concept demo is live at a specific URL, invite them to \
look at it using that exact URL, reproduced exactly as given -- do not \
alter, shorten, retype, or paraphrase it. Use it in the initial email body \
and in both follow-up emails. Never include a link, or imply one exists, \
in the SMS -- keep the SMS pitch link-free regardless of whether a demo is \
live, mentioning only that a concept has been put together and inviting a \
reply.

If no demo is live yet (either none has been built, or it exists but isn't \
hosted), do not include a link or imply one exists anywhere -- keep the \
"take a look" language general (e.g. inviting them to reply to see it) \
rather than pointing at something that doesn't exist yet.

Tone: direct, low-pressure, plainly written -- like a local business owner \
reaching out, not a marketing agency. No exclamation-point energy, no fake \
urgency, no "act now" language.

When you're given specific technical problems found on a shop's existing \
site, reference the real, specific issue(s) you were given -- not generic \
catch-all phrasing like "not mobile-friendly, or similar." Don't imply \
there are more problems than what was actually listed; if only one issue \
was found, mention only that one.

Compliance requirements (non-negotiable, this is a real legal concern, not \
boilerplate):
- The email must NOT contain a deceptive or clickbait subject line -- it \
  must accurately describe the email's content.
- The email body must end with these exact literal placeholder tokens, each \
  on their own line, for the human sender to fill in before sending: \
  {{SENDER_NAME}}, {{SENDER_COMPANY}}, {{SENDER_PHYSICAL_ADDRESS}}, and a \
  final line reading "Don't want these emails? {{UNSUBSCRIBE_LINK}}"
- The SMS must end with "Reply STOP to opt out." literally, and must \
  identify the sender by including {{SENDER_COMPANY}} in the body.
- Keep the SMS under 320 characters including the opt-out line.
- Every follow-up must ALSO include the same footer/opt-out requirements as \
  the initial email.

Write exactly 2 follow-up emails: one for a lead who never replied, one for \
a lead who's clearly gone cold. Space them out realistically (a few days, \
then another week-plus) -- put the actual day offsets in the day_offset \
field."""


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
    """Demo status: three real states, not a bool -- see demo_url_for()."""
    if demo_url:
        return (
            f"A concept demo is live for this shop at {demo_url} -- reference "
            "this exact URL in the email (and follow-ups) when inviting them to look."
        )
    if demo_exists:
        return "A concept demo has been built for this shop but isn't hosted/live yet -- do not include a link."
    return "No concept demo has been built for this shop yet."


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "subject_line": {"type": "string"},
        "email_body": {"type": "string"},
        "sms_body": {"type": "string"},
        "followups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "day_offset": {"type": "integer", "description": "Days after the initial email"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["day_offset", "subject", "body"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["subject_line", "email_body", "sms_body", "followups"],
    "additionalProperties": False,
}


def describe_website_issues(signals_json: str | None) -> list[str]:
    """Turn Discovery's stored site_check.py findings into plain-language,
    per-shop-specific issues -- real findings only, never generic filler."""
    if not signals_json:
        return []
    try:
        signals = json.loads(signals_json)
    except (TypeError, json.JSONDecodeError):
        return []

    issues = []
    if signals.get("not_https"):
        issues.append('it loads over plain HTTP, not HTTPS, so browsers flag it as "Not Secure"')
    if signals.get("missing_viewport_meta"):
        issues.append("it has no mobile viewport tag, so it won't resize properly on a phone")
    stale_year = signals.get("stale_copyright_year")
    if stale_year:
        issues.append(f"the footer copyright year is still stuck on {stale_year}")
    splash = signals.get("builder_splash_marker")
    if splash:
        issues.append(f'it still shows a builder placeholder page ("{splash}"), like it was never finished')
    tech = signals.get("stale_tech_marker")
    if tech:
        issues.append(f'the page still has leftover legacy markup ("{tech}")')
    return issues


def build_user_prompt(lead: sqlite3.Row, demo_exists: bool, demo_url: str | None) -> str:
    qualification = lead["qualification_status"]
    if qualification == "qualified_no_website":
        situation = "This shop has no website at all listed on Google."
    else:
        issues = describe_website_issues(lead["website_signals"])
        if issues:
            situation = f"This shop has a website ({lead['website_url']}). An automated check found: {'; '.join(issues)}."
        else:
            situation = f"This shop has a website ({lead['website_url']}), but it's outdated."

    return f"""Shop name: {lead['business_name']}
City/State: {lead['city']}, {lead['state']}
Phone (from Google listing, public): {lead['phone']}
Situation: {situation}
Demo status: {demo_status_line(demo_exists, demo_url)}

Write the outreach copy now."""


def generate_draft(client: Anthropic, lead: sqlite3.Row, demo_exists: bool, demo_url: str | None) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        # effort=medium: verified via a live medium-vs-high comparison (no tools
        # involved here, so lower effort just means less output, no downside
        # found) -- ~20% fewer output tokens, no quality loss observed. See
        # ARCHITECTURE.md Section 12. Do NOT copy this to the Dossier agent --
        # its web_search tool made medium effort MORE expensive there, not less.
        output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}, "effort": "medium"},
        messages=[{"role": "user", "content": build_user_prompt(lead, demo_exists, demo_url)}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def render_markdown(lead: sqlite3.Row, draft: dict) -> str:
    lines = [
        f"# Outreach draft: {lead['business_name']}",
        "",
        f"**Status:** DRAFT -- not reviewed, not approved, not sent.",
        f"**Lead:** {lead['business_name']} -- {lead['city']}, {lead['state']} -- {lead['phone']}",
        f"**Qualification:** {lead['qualification_status']}",
        "",
        "Fill in every `{{TOKEN}}` placeholder before this goes anywhere near a send.",
        "",
        "## Initial Email",
        "",
        f"**Subject:** {draft['subject_line']}",
        "",
        draft["email_body"],
        "",
        "## SMS",
        "",
        "> **Before using this:** cold SMS to a number scraped from a business listing carries real TCPA risk -- see README.md. Get this reviewed before it's ever sent.",
        "",
        draft["sms_body"],
        "",
        "## Follow-up Schedule",
        "",
    ]
    for i, followup in enumerate(draft["followups"], start=1):
        lines += [
            f"### Follow-up {i} -- Day {followup['day_offset']}",
            "",
            f"**Subject:** {followup['subject']}",
            "",
            followup["body"],
            "",
        ]
    return "\n".join(lines)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Outreach Copywriting Agent")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to Discovery Agent's leads.db")
    parser.add_argument("--suppression-db", type=Path, default=DEFAULT_SUPPRESSION_DB, help="Path to the suppression list db")
    parser.add_argument("--demo-dir", type=Path, default=DEFAULT_DEMO_DIR, help="Path to Website Demo Generation Agent's output directory")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Where to write drafts")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N qualified leads")
    parser.add_argument("--force", action="store_true", help="Regenerate drafts that already exist")
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"leads.db not found at {args.db} -- run the Discovery Agent first")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY not set -- add it to .env")

    site_base_url = os.environ.get("DEMO_SITE_BASE_URL", "").strip() or None

    client = Anthropic(api_key=api_key)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    suppression_db.init_db(str(args.suppression_db))
    suppression_conn = suppression_db.get_connection(str(args.suppression_db))

    leads = fetch_qualified_leads(args.db, args.limit)
    print(f"{len(leads)} qualified lead(s) found")

    generated, skipped, suppressed = 0, 0, 0
    for lead in leads:
        slug = slugify(lead["business_name"], lead["city"] or "")
        dest = args.output_dir / slug / "draft.md"

        if dest.exists() and not args.force:
            skipped += 1
            print(f"  {lead['business_name']} -> {dest} (already existed, skipped)")
            continue

        if lead["phone"] and suppression_db.is_suppressed(suppression_conn, "phone", lead["phone"]):
            suppressed += 1
            print(f"  {lead['business_name']} -> SKIPPED (phone is on the suppression list)")
            continue

        demo_exists = (args.demo_dir / slug).exists()
        demo_url = demo_url_for(lead["business_name"], lead["city"] or "", args.demo_dir, site_base_url)

        draft = generate_draft(client, lead, demo_exists, demo_url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render_markdown(lead, draft), encoding="utf-8")
        # Structured sidecar -- draft.md is for a human to read; draft.json is
        # for tools (e.g. the follow-up scheduler) that need the day_offset
        # data without parsing markdown.
        (dest.parent / "draft.json").write_text(json.dumps(draft, indent=2), encoding="utf-8")

        generated += 1
        print(f"  {lead['business_name']} -> {dest}")

    suppression_conn.close()
    print(f"\nDone. {generated} generated, {skipped} skipped (already existed), {suppressed} skipped (suppressed), output in {args.output_dir}")


if __name__ == "__main__":
    main()
