"""Follow-up Scheduler.

Outreach drafts follow-ups with day_offset values ("day 4", "day 16") but
has no idea when -- or whether -- anything actually got sent, because
sending doesn't exist in this system yet. This tool is the missing piece:
a human records what they actually sent and when (`mark-sent`), and this
computes what's due next, anchored to the real send date rather than a
guess.

Correctly stops scheduling for any lead that's suppressed (opted out) or
has any reply logged at all -- once a real conversation has started,
automated follow-ups should stop, regardless of what the reply said.

Usage:
    python scheduler_cli.py mark-sent --business "Village Tattoo NYC" --channel email
    python scheduler_cli.py mark-sent --business "Village Tattoo NYC" --followup 1 --date 2026-08-04
    python scheduler_cli.py due
    python scheduler_cli.py upcoming --days 7
"""

import argparse
import datetime
import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path


def _load_module(name: str, path: Path):
    """Load a module by explicit file path under a distinct internal name --
    several sibling agent folders each have their own db.py, so a plain
    `import db` would collide."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).parent.parent
scheduler_db = _load_module("scheduler_db_module", Path(__file__).parent / "db.py")
suppression_db = _load_module("suppression_db_module", ROOT / "suppression" / "db.py")
reply_db = _load_module("reply_db_module", ROOT / "reply_triage" / "db.py")

DEFAULT_LEADS_DB = ROOT / "discovery" / "leads.db"
DEFAULT_SUPPRESSION_DB = ROOT / "suppression" / "suppression.db"
DEFAULT_REPLIES_DB = ROOT / "reply_triage" / "replies.db"
DEFAULT_SENDS_DB = Path(__file__).parent / "sends.db"
DEFAULT_DRAFTS_DIR = ROOT / "outreach" / "drafts"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def slugify(business_name: str, city: str) -> str:
    raw = f"{business_name}-{city}"
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug or "lead"


def lookup_lead(db_path: Path, business: str | None, phone: str | None) -> sqlite3.Row | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if business:
        row = conn.execute("SELECT * FROM leads WHERE LOWER(business_name) = LOWER(?)", (business,)).fetchone()
    else:
        target_digits = re.sub(r"\D", "", phone or "")
        row = None
        for candidate in conn.execute("SELECT * FROM leads").fetchall():
            if re.sub(r"\D", "", candidate["phone"] or "")[-10:] == target_digits[-10:]:
                row = candidate
                break
    conn.close()
    return row


def cmd_mark_sent(args: argparse.Namespace) -> None:
    lead = lookup_lead(args.leads_db, args.business, args.phone)
    if lead is None:
        raise SystemExit("No matching lead found -- check --business spelling or --phone digits")

    slug = slugify(lead["business_name"], lead["city"] or "")
    sent_date = args.date or datetime.date.today().isoformat()

    conn = scheduler_db.get_connection(str(args.sends_db))
    scheduler_db.mark_sent(conn, slug, lead["business_name"], args.channel, args.followup, sent_date)
    conn.close()

    label = "initial send" if args.followup == 0 else f"follow-up {args.followup}"
    print(f"Recorded {label} for {lead['business_name']} via {args.channel} on {sent_date}")


def compute_schedule(args: argparse.Namespace, as_of: datetime.date) -> list[dict]:
    sends_conn = scheduler_db.get_connection(str(args.sends_db))
    suppression_conn = suppression_db.get_connection(str(args.suppression_db))
    replies_conn = reply_db.get_connection(str(args.replies_db))

    results = []
    for slug in scheduler_db.get_all_leads_with_sends(sends_conn):
        sends = scheduler_db.get_sends_for_lead(sends_conn, slug)
        initial = next((s for s in sends if s["followup_index"] == 0), None)
        if initial is None:
            continue  # no anchor to schedule from

        business_name = initial["business_name"]

        lead = lookup_lead(args.leads_db, business_name, None)
        if lead and lead["phone"] and suppression_db.is_suppressed(suppression_conn, "phone", lead["phone"]):
            continue  # opted out -- never schedule further contact

        if reply_db.list_replies(replies_conn, slug):
            continue  # any reply at all means a real conversation has started; stop the automated drip

        draft_json_path = args.drafts_dir / slug / "draft.json"
        if not draft_json_path.exists():
            continue  # can't compute without the structured follow-up data

        followups = json.loads(draft_json_path.read_text(encoding="utf-8"))["followups"]
        max_sent_index = max(s["followup_index"] for s in sends)
        next_index = max_sent_index + 1

        if next_index > len(followups):
            continue  # fully followed up, nothing left scheduled

        followup = followups[next_index - 1]
        initial_date = datetime.date.fromisoformat(initial["sent_at"])
        due_date = initial_date + datetime.timedelta(days=followup["day_offset"])
        days_until_due = (due_date - as_of).days

        results.append({
            "business_name": business_name,
            "slug": slug,
            "followup_index": next_index,
            "subject": followup["subject"],
            "due_date": due_date.isoformat(),
            "days_until_due": days_until_due,
        })

    sends_conn.close()
    suppression_conn.close()
    replies_conn.close()
    return sorted(results, key=lambda r: r["days_until_due"])


def _print_schedule(rows: list[dict]) -> None:
    if not rows:
        print("Nothing to show.")
        return
    for r in rows:
        status = "OVERDUE" if r["days_until_due"] < 0 else ("DUE TODAY" if r["days_until_due"] == 0 else f"in {r['days_until_due']}d")
        print(f"  [{status:9s}] {r['business_name']:35s} follow-up {r['followup_index']} due {r['due_date']} -- \"{r['subject']}\"")
    print(f"\n{len(rows)} total")


def cmd_due(args: argparse.Namespace) -> None:
    as_of = datetime.date.fromisoformat(args.as_of) if args.as_of else datetime.date.today()
    rows = [r for r in compute_schedule(args, as_of) if r["days_until_due"] <= 0]
    _print_schedule(rows)


def cmd_upcoming(args: argparse.Namespace) -> None:
    as_of = datetime.date.fromisoformat(args.as_of) if args.as_of else datetime.date.today()
    rows = [r for r in compute_schedule(args, as_of) if r["days_until_due"] <= args.days]
    _print_schedule(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Follow-up Scheduler")
    parser.add_argument("--leads-db", type=Path, default=DEFAULT_LEADS_DB)
    parser.add_argument("--suppression-db", type=Path, default=DEFAULT_SUPPRESSION_DB)
    parser.add_argument("--replies-db", type=Path, default=DEFAULT_REPLIES_DB)
    parser.add_argument("--sends-db", type=Path, default=DEFAULT_SENDS_DB)
    parser.add_argument("--drafts-dir", type=Path, default=DEFAULT_DRAFTS_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    p_mark = sub.add_parser("mark-sent")
    contact = p_mark.add_mutually_exclusive_group(required=True)
    contact.add_argument("--business")
    contact.add_argument("--phone")
    p_mark.add_argument("--channel", required=True, choices=["email", "sms"])
    p_mark.add_argument("--followup", type=int, default=0, help="0 = initial send, 1+ = follow-up N (default 0)")
    p_mark.add_argument("--date", default=None, help="ISO date, defaults to today")
    p_mark.set_defaults(func=cmd_mark_sent)

    p_due = sub.add_parser("due")
    p_due.add_argument("--as-of", default=None, help="ISO date, defaults to today")
    p_due.set_defaults(func=cmd_due)

    p_upcoming = sub.add_parser("upcoming")
    p_upcoming.add_argument("--days", type=int, default=7)
    p_upcoming.add_argument("--as-of", default=None)
    p_upcoming.set_defaults(func=cmd_upcoming)

    args = parser.parse_args()
    scheduler_db.init_db(str(args.sends_db))
    args.func(args)


if __name__ == "__main__":
    main()
