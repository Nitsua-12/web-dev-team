"""Reply Triage.

There's no live inbox or SMS line connected to this system -- sending
doesn't exist yet, so nothing can watch for replies automatically. This is
the tool a human runs the moment they personally see a reply (in their own
email client, phone, wherever) to get Claude's read on it and have the
system react appropriately: auto-suppress on opt-out language, and flag
the lead's dossier for follow-up on anything that needs a human.

Usage:
    python triage_cli.py --business "Addiction NYC" --channel sms --text "Reply STOP"
    python triage_cli.py --phone "917-500-8489" --channel email --text "Sure, send it over!"
"""

import argparse
import datetime
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
    """Load a module by explicit file path under a distinct internal name --
    this folder and agents/suppression both have their own db.py, so a plain
    `import db` would collide (whichever loads first wins for both)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


suppression_db = _load_module("suppression_db_module", Path(__file__).parent.parent / "suppression" / "db.py")
reply_db = _load_module("reply_triage_db_module", Path(__file__).parent / "db.py")

MODEL = "claude-sonnet-5"
DEFAULT_LEADS_DB = Path(__file__).parent.parent / "discovery" / "leads.db"
DEFAULT_SUPPRESSION_DB = Path(__file__).parent.parent / "suppression" / "suppression.db"
DEFAULT_REPLIES_DB = Path(__file__).parent / "replies.db"
DEFAULT_DOSSIER_DIR = Path(__file__).parent.parent / "dossier" / "dossiers"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "classification": {
            "type": "string",
            "enum": ["opt_out", "interested", "not_interested", "question", "unclear"],
        },
        "summary": {"type": "string", "description": "One sentence on what the reply actually says."},
    },
    "required": ["classification", "summary"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You classify a reply to a cold outreach message. The \
original message told a tattoo shop owner that a modern website concept had \
been put together for their shop and asked if they wanted to see it (sent \
by email or SMS).

Classify the reply into exactly one category:
- opt_out: any request to stop contact -- "STOP", "unsubscribe", "remove me", \
  "stop texting/emailing me", explicit refusal to be contacted again
- interested: positive response, wants to see the demo or talk further
- not_interested: a polite decline that is NOT a request to stop contact \
  (e.g. "not right now", "we're good")
- question: asks something that needs an answer before they'll decide
- unclear: genuinely ambiguous, can't confidently pick another category

Write a one-sentence summary of what the reply actually says. Do not add \
interpretation beyond what's in the text."""


def slugify(business_name: str, city: str) -> str:
    raw = f"{business_name}-{city}"
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug or "lead"


def lookup_lead(db_path: Path, business: str | None, phone: str | None) -> sqlite3.Row | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if business:
        row = conn.execute(
            "SELECT * FROM leads WHERE LOWER(business_name) = LOWER(?)", (business,)
        ).fetchone()
    else:
        target_digits = re.sub(r"\D", "", phone or "")
        row = None
        for candidate in conn.execute("SELECT * FROM leads").fetchall():
            if re.sub(r"\D", "", candidate["phone"] or "")[-10:] == target_digits[-10:]:
                row = candidate
                break
    conn.close()
    return row


def classify_reply(client: Anthropic, channel: str, text: str) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": CLASSIFY_SCHEMA}},
        messages=[{"role": "user", "content": f"Channel: {channel}\nReply text:\n{text}"}],
    )
    text_block = next(b.text for b in response.content if b.type == "text")
    return json.loads(text_block)


def take_action(lead: sqlite3.Row, channel: str, classification: str, suppression_conn: sqlite3.Connection) -> str:
    if classification == "opt_out":
        reason = "stop_reply" if channel == "sms" else ("unsubscribe" if channel == "email" else "manual")
        if lead["phone"]:
            normalized = suppression_db.add_suppression(
                suppression_conn, "phone", lead["phone"], reason, source=f"{channel}_reply",
                notes="Auto-suppressed by reply_triage on opt-out language",
            )
            return f"added to suppression list ({reason}, {normalized})"
        return "opt-out detected but lead has no phone on file -- could not suppress"
    if classification == "interested":
        return "flagged in dossier for human follow-up"
    if classification == "not_interested":
        return "logged; not auto-suppressed (not a legal opt-out) -- human can decide whether to stop follow-ups"
    if classification == "question":
        return "flagged in dossier -- needs a human answer"
    return "flagged in dossier for human review (unclear)"


def update_dossier(dossier_path: Path, business_name: str, channel: str, text: str, classification: str, summary: str) -> bool:
    if not dossier_path.exists():
        return False

    timestamp = datetime.date.today().isoformat()
    flag_block = (
        f"\n## NEW REPLY -- ACTION NEEDED ({timestamp})\n\n"
        f"**Channel:** {channel}\n"
        f"**Classification:** {classification.upper()}\n\n"
        f"> {text}\n\n"
        f"Summary: {summary}\n"
    )

    original = dossier_path.read_text(encoding="utf-8")
    marker = "**For internal use by the human salesperson only.**"
    if marker in original:
        idx = original.index(marker) + len(marker)
        # skip to end of that line before inserting
        line_end = original.index("\n", idx)
        updated = original[: line_end + 1] + flag_block + original[line_end + 1:]
    else:
        updated = flag_block + "\n" + original

    dossier_path.write_text(updated, encoding="utf-8")
    return True


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Reply Triage -- log and classify a reply a human personally saw")
    parser.add_argument("--leads-db", type=Path, default=DEFAULT_LEADS_DB)
    parser.add_argument("--suppression-db", type=Path, default=DEFAULT_SUPPRESSION_DB)
    parser.add_argument("--replies-db", type=Path, default=DEFAULT_REPLIES_DB)
    parser.add_argument("--dossier-dir", type=Path, default=DEFAULT_DOSSIER_DIR)
    contact = parser.add_mutually_exclusive_group(required=True)
    contact.add_argument("--business", help="Exact business name as it appears in leads.db")
    contact.add_argument("--phone", help="Lead's phone number, any format")
    parser.add_argument("--channel", required=True, choices=["email", "sms", "phone_call"])
    parser.add_argument("--text", required=True, help="The reply text (or a written summary of a phone call)")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY not set -- add it to .env")

    lead = lookup_lead(args.leads_db, args.business, args.phone)
    if lead is None:
        raise SystemExit("No matching lead found in leads.db -- check --business spelling or --phone digits")

    client = Anthropic(api_key=api_key)
    result = classify_reply(client, args.channel, args.text)
    classification, summary = result["classification"], result["summary"]

    suppression_db.init_db(str(args.suppression_db))
    suppression_conn = suppression_db.get_connection(str(args.suppression_db))
    action = take_action(lead, args.channel, classification, suppression_conn)
    suppression_conn.close()

    reply_db.init_db(str(args.replies_db))
    reply_conn = reply_db.get_connection(str(args.replies_db))
    slug = slugify(lead["business_name"], lead["city"] or "")
    reply_db.add_reply(reply_conn, slug, lead["business_name"], args.channel, args.text, classification, summary, action)
    reply_conn.close()

    dossier_path = args.dossier_dir / slug / "dossier.md"
    dossier_updated = update_dossier(dossier_path, lead["business_name"], args.channel, args.text, classification, summary)

    print(f"Lead: {lead['business_name']}")
    print(f"Classification: {classification.upper()}")
    print(f"Summary: {summary}")
    print(f"Action taken: {action}")
    print(f"Dossier updated: {'yes -> ' + str(dossier_path) if dossier_updated else 'no dossier exists yet for this lead -- run the Dossier agent first'}")


if __name__ == "__main__":
    main()
