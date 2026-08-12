"""Lead Re-verification Agent.

A qualified_no_website lead discovered weeks ago might have a real site
by the time outreach actually happens; a qualified_outdated lead's site
might have been fixed. Pitching either as-is means arguing from stale
facts. This re-checks currently-active leads against Google and, if the
underlying situation changed, updates leads.db in place -- the same
qualification_status field every other agent in this pipeline reads.

Reuses Discovery's own Places API client and website heuristic checker
(imported directly by file path, not duplicated) so re-verification uses
the exact same classification logic as the original discovery, not a
second implementation that could drift from it.

No LLM calls -- like Discovery itself, this is pure API + rule-based
classification, deterministic and cheap.

Usage:
    python reverify.py --dry-run                      # see what would change, save nothing
    python reverify.py --limit 3                        # smoke test
    python reverify.py                                   # full run, skips leads checked in the last 7 days
    python reverify.py --min-days-since-check 0          # force-recheck everyone regardless of last check
"""

import argparse
import datetime
import importlib.util
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).parent.parent
places_client = _load_module("discovery_places_client_module", ROOT / "discovery" / "places_client.py")
site_check = _load_module("discovery_site_check_module", ROOT / "discovery" / "site_check.py")
discovery_db = _load_module("discovery_db_module", ROOT / "discovery" / "db.py")
reverify_db = _load_module("reverify_db_module", Path(__file__).parent / "db.py")

DEFAULT_LEADS_DB = ROOT / "discovery" / "leads.db"
DEFAULT_LOG_DB = Path(__file__).parent / "reverify_log.db"
ACTIVE_STATUSES = ("qualified_no_website", "qualified_outdated")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def classify_website(url: str | None) -> tuple[str, str]:
    """Mirrors discovery_agent.py's _place_to_lead classification exactly,
    so a lead re-checked here lands in the same bucket a fresh Discovery
    run would put it in."""
    if not url:
        return "none", "qualified_no_website"
    result = site_check.check_website(url)
    status = result["status"]
    if status == "outdated":
        return status, "qualified_outdated"
    if status == "modern":
        return status, "disqualified_modern"
    return status, "needs_review"  # unknown (robots-blocked) or error


def apply_lead_update(
    leads_conn: sqlite3.Connection,
    google_place_id: str,
    new_url: str | None,
    new_website_status: str,
    new_qualification: str,
) -> None:
    """Writes a re-verified lead's new status to leads.db. Also resets the
    website-audit columns (audit_status/audit_score/audit_signals/audit_run_at,
    added by agents/discovery/site_audit.py) -- a qualification_status change
    means any prior audit no longer reflects this lead's current state, and
    would otherwise sit as stale evidence in Outreach/Dossier prompts."""
    leads_conn.execute(
        """
        UPDATE leads
        SET website_url = ?, has_website = ?, website_status = ?, qualification_status = ?,
            audit_status = 'not_run', audit_score = NULL, audit_signals = NULL, audit_run_at = NULL
        WHERE google_place_id = ?
        """,
        (new_url, int(bool(new_url)), new_website_status, new_qualification, google_place_id),
    )
    leads_conn.commit()


def fetch_active_leads(leads_db: Path, log_db: Path, min_days_since_check: int, limit: int | None) -> list[sqlite3.Row]:
    conn = sqlite3.connect(leads_db)
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
    rows = conn.execute(
        f"SELECT * FROM leads WHERE qualification_status IN ({placeholders}) ORDER BY id", ACTIVE_STATUSES
    ).fetchall()
    conn.close()

    if min_days_since_check > 0:
        log_conn = reverify_db.get_connection(str(log_db))
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=min_days_since_check)
        filtered = []
        for row in rows:
            last = reverify_db.get_last_checked(log_conn, row["google_place_id"])
            if last is None or datetime.datetime.fromisoformat(last) < cutoff:
                filtered.append(row)
        log_conn.close()
        rows = filtered

    return rows[:limit] if limit else rows


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Lead Re-verification Agent")
    parser.add_argument("--db", type=Path, default=DEFAULT_LEADS_DB)
    parser.add_argument("--log-db", type=Path, default=DEFAULT_LOG_DB)
    parser.add_argument("--min-days-since-check", type=int, default=7, help="Skip leads checked within the last N days (0 = always recheck)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without saving anything")
    args = parser.parse_args()

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    if not api_key:
        raise SystemExit("GOOGLE_PLACES_API_KEY not set -- add it to .env")

    reverify_db.init_db(str(args.log_db))
    # Ensures leads.db has the website-audit columns (audit_status/audit_score/
    # audit_signals/audit_run_at) before apply_lead_update ever references
    # them -- reverify.py can run against a leads.db that hasn't had
    # discovery_agent.py's own init_db() called on it recently (or ever),
    # since the two agents write to the same file independently. Only
    # needed on the live-write path: dry-run never calls apply_lead_update,
    # so running this here too would silently ALTER TABLE a file the tool
    # promises to leave untouched in dry-run mode.
    if not args.dry_run:
        discovery_db.init_db(str(args.db))
    log_conn = reverify_db.get_connection(str(args.log_db))
    leads_conn = sqlite3.connect(args.db)
    leads_conn.row_factory = sqlite3.Row

    leads = fetch_active_leads(args.db, args.log_db, args.min_days_since_check, args.limit)
    print(f"{len(leads)} active lead(s) to re-verify (min_days_since_check={args.min_days_since_check}, dry_run={args.dry_run})")

    changed_count = 0
    for lead in leads:
        try:
            details = places_client.get_place_details(lead["google_place_id"], api_key)
        except places_client.PlacesApiError as exc:
            print(f"  {lead['business_name']}: ERROR fetching place details -- {exc}")
            continue

        new_url = details.get("websiteUri")
        new_website_status, new_qualification = classify_website(new_url)
        changed = new_qualification != lead["qualification_status"]

        reverify_db.log_check(
            log_conn, lead["google_place_id"], lead["business_name"],
            lead["qualification_status"], new_qualification,
            lead["website_url"], new_url, changed,
        )

        if changed:
            changed_count += 1
            suffix = " (dry-run, not saved)" if args.dry_run else ""
            print(f"  {lead['business_name']}: CHANGED {lead['qualification_status']} -> {new_qualification}{suffix}")
            if not args.dry_run:
                apply_lead_update(leads_conn, lead["google_place_id"], new_url, new_website_status, new_qualification)
        else:
            print(f"  {lead['business_name']}: no change ({lead['qualification_status']})")

    leads_conn.close()
    log_conn.close()

    print(f"\nDone. {len(leads)} checked, {changed_count} changed" + (" (dry-run: leads.db untouched)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
