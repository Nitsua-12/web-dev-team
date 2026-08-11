"""Outcome Feedback Loop.

There's no automated way to know a deal closed -- that only happens in a
real conversation, after the human takes over per the Sales Handoff
Dossier. `record` is how a human logs the final result. `report` shows
the real funnel across every stage this pipeline can actually measure:
sent -> replied -> outcome.

No API keys, no pip dependencies beyond the stdlib.

Usage:
    python outcomes_cli.py record --business "Village Tattoo NYC" --outcome won --value 450 --notes "Signed after a call"
    python outcomes_cli.py record --business "Some Shop" --outcome lost --notes "Went with a competitor"
    python outcomes_cli.py report
"""

import argparse
import re
import sqlite3
import sys
from pathlib import Path

import db
import stats

ROOT = Path(__file__).parent.parent
DEFAULT_LEADS_DB = ROOT / "discovery" / "leads.db"
DEFAULT_OUTCOMES_DB = Path(__file__).parent / "outcomes.db"
DEFAULT_SENDS_DB = ROOT / "scheduler" / "sends.db"
DEFAULT_REPLIES_DB = ROOT / "reply_triage" / "replies.db"

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


def cmd_record(args: argparse.Namespace) -> None:
    lead = lookup_lead(args.leads_db, args.business, args.phone)
    if lead is None:
        raise SystemExit("No matching lead found -- check --business spelling or --phone digits")

    slug = slugify(lead["business_name"], lead["city"] or "")
    conn = db.get_connection(str(args.outcomes_db))
    db.record_outcome(conn, slug, lead["business_name"], args.outcome, args.value, args.notes)
    conn.close()

    print(f"Recorded outcome for {lead['business_name']}: {args.outcome}" + (f" (${args.value:.2f})" if args.value else ""))


def cmd_report(args: argparse.Namespace) -> None:
    f = stats.compute_funnel(args.sends_db, args.replies_db, args.outcomes_db)

    print("Outreach funnel (across every lead this pipeline has real data for)")
    print(f"  Sent (initial):      {f['total_sent']}")
    print(f"  Replied:             {f['total_replied']}")
    if f["reply_breakdown"]:
        for classification, count in sorted(f["reply_breakdown"].items()):
            print(f"    {classification:15s} {count}")
    print(f"  Outcomes recorded:   {f['total_outcomes_recorded']}")
    if f["outcome_breakdown"]:
        for outcome, count in sorted(f["outcome_breakdown"].items()):
            print(f"    {outcome:15s} {count}")
    if f["avg_won_value"] is not None:
        print(f"  Avg. won deal value: ${f['avg_won_value']:.2f}")

    if f["total_sent"] == 0:
        print("\nNo sends recorded yet -- this report has nothing real to show until outreach actually goes out.")
    elif not f["outcome_sample_meaningful"]:
        print(f"\nOnly {f['total_outcomes_recorded']} outcome(s) recorded -- too few to treat any rate here as statistically meaningful. Directional at best.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Outcome Feedback Loop")
    parser.add_argument("--leads-db", type=Path, default=DEFAULT_LEADS_DB)
    parser.add_argument("--outcomes-db", type=Path, default=DEFAULT_OUTCOMES_DB)
    parser.add_argument("--sends-db", type=Path, default=DEFAULT_SENDS_DB)
    parser.add_argument("--replies-db", type=Path, default=DEFAULT_REPLIES_DB)
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser("record")
    contact = p_record.add_mutually_exclusive_group(required=True)
    contact.add_argument("--business")
    contact.add_argument("--phone")
    p_record.add_argument("--outcome", required=True, choices=sorted(db.VALID_OUTCOMES))
    p_record.add_argument("--value", type=float, default=None, help="Actual deal size in dollars, if won")
    p_record.add_argument("--notes", default=None)
    p_record.set_defaults(func=cmd_record)

    p_report = sub.add_parser("report")
    p_report.set_defaults(func=cmd_report)

    args = parser.parse_args()
    db.init_db(str(args.outcomes_db))
    args.func(args)


if __name__ == "__main__":
    main()
