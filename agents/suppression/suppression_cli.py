"""Suppression list CLI. No API keys, no dependencies beyond the Python
standard library -- this only touches a local SQLite file.

Real opt-outs mostly arrive as a human hearing "stop calling/texting me" on
the phone, or reading a reply -- there's no automated trigger for those yet,
so `add` exists for a human to record them directly.

Usage:
    python suppression_cli.py add --phone "(212) 555-0100" --reason manual --source phone_call --notes "asked us to stop during a call"
    python suppression_cli.py add --email jane@shop.com --reason unsubscribe --source email_reply
    python suppression_cli.py check --phone "212-555-0100"
    python suppression_cli.py list
    python suppression_cli.py remove --phone "212-555-0100"   # corrections only
"""

import argparse
import sys
from pathlib import Path

import db

DEFAULT_DB = Path(__file__).parent / "suppression.db"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def cmd_add(args: argparse.Namespace) -> None:
    contact_type, raw_value = ("phone", args.phone) if args.phone else ("email", args.email)
    conn = db.get_connection(str(args.db))
    normalized = db.add_suppression(conn, contact_type, raw_value, args.reason, args.source, args.notes)
    conn.close()
    print(f"Suppressed {contact_type}: {normalized} (reason: {args.reason})")


def cmd_check(args: argparse.Namespace) -> None:
    contact_type, raw_value = ("phone", args.phone) if args.phone else ("email", args.email)
    conn = db.get_connection(str(args.db))
    suppressed = db.is_suppressed(conn, contact_type, raw_value)
    conn.close()
    print("SUPPRESSED" if suppressed else "not suppressed")
    sys.exit(1 if suppressed else 0)


def cmd_list(args: argparse.Namespace) -> None:
    conn = db.get_connection(str(args.db))
    rows = db.list_suppressions(conn)
    conn.close()
    if not rows:
        print("No suppressions recorded.")
        return
    for row in rows:
        print(f"{row['added_at']}  {row['contact_type']:5s}  {row['contact_value']:16s}  {row['reason']:15s}  source={row['source']}  notes={row['notes']}")
    print(f"\n{len(rows)} total")


def cmd_remove(args: argparse.Namespace) -> None:
    contact_type, raw_value = ("phone", args.phone) if args.phone else ("email", args.email)
    conn = db.get_connection(str(args.db))
    removed = db.remove_suppression(conn, contact_type, raw_value)
    conn.close()
    print("Removed." if removed else "No matching entry found.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Suppression list -- manage opt-outs")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)

    for name, fn, needs_reason in [("add", cmd_add, True), ("check", cmd_check, False), ("remove", cmd_remove, False)]:
        p = sub.add_parser(name)
        contact = p.add_mutually_exclusive_group(required=True)
        contact.add_argument("--phone")
        contact.add_argument("--email")
        if needs_reason:
            p.add_argument("--reason", required=True, choices=sorted(db.VALID_REASONS))
            p.add_argument("--source", default=None)
            p.add_argument("--notes", default=None)
        p.set_defaults(func=fn)

    p_list = sub.add_parser("list")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    db.init_db(str(args.db))
    args.func(args)


if __name__ == "__main__":
    main()
