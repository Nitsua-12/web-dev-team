"""Discovery Agent: finds tattoo shops via Google Places, flags the ones that
either have no website or have an outdated one, and writes structured leads
to a local SQLite database.

Usage:
    python discovery_agent.py --limit-cities 3          # small real test
    python discovery_agent.py                           # full seed batch
    python discovery_agent.py --dry-run                 # no API calls, fake data

Requires GOOGLE_PLACES_API_KEY in a .env file (see .env.example) unless
--dry-run is passed. PSI_API_KEY is also read, for the website-audit step
on qualified_outdated leads (see site_audit.py) -- not required to run
this script at all, just to get real Core Web Vitals data instead of a
per-lead "audit: error" line.
"""

import argparse
import datetime
import os
import sys

# Windows consoles default to a codepage (cp1252) that can't encode every
# character Places API returns in business names (curly quotes, accents,
# etc.) -- reconfigure stdout so those print as best-effort instead of
# crashing the whole batch partway through.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

import db
import places_client
import site_audit
import site_check
from cities_seed import DEFAULT_RADIUS_M, SEED_CITIES

DB_PATH_DEFAULT = "leads.db"

FAKE_PLACES_FOR_DRY_RUN = [
    {
        "id": "dry-run-place-1",
        "displayName": {"text": "Old School Ink"},
        "formattedAddress": "123 Example St, Springfield, IL 62701",
        "websiteUri": "http://example.com",
        "nationalPhoneNumber": "(217) 555-0100",
        "addressComponents": [
            {"types": ["locality"], "shortText": "Springfield"},
            {"types": ["administrative_area_level_1"], "shortText": "IL"},
            {"types": ["postal_code"], "shortText": "62701"},
        ],
    },
    {
        "id": "dry-run-place-2",
        "displayName": {"text": "No Website Tattoo Co"},
        "formattedAddress": "456 Sample Ave, Springfield, IL 62701",
        "addressComponents": [
            {"types": ["locality"], "shortText": "Springfield"},
            {"types": ["administrative_area_level_1"], "shortText": "IL"},
            {"types": ["postal_code"], "shortText": "62701"},
        ],
    },
]


def run(db_path: str, limit_cities: int | None, dry_run: bool, state_filter: str | None) -> None:
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    psi_api_key = os.environ.get("PSI_API_KEY", "")
    if not dry_run and not psi_api_key:
        print("WARNING: PSI_API_KEY is not set. Website audits will fail for every qualified_outdated lead this run.")
    db.init_db(db_path)
    conn = db.get_connection(db_path)

    cities = SEED_CITIES
    if state_filter:
        cities = [c for c in cities if c[1].upper() == state_filter.upper()]
    if limit_cities:
        cities = cities[:limit_cities]

    for city, state, lat, lng in cities:
        label = f"{city}, {state}"
        db.upsert_search_cell(conn, label, state, lat, lng, DEFAULT_RADIUS_M)

    pending = db.get_pending_cells(conn)
    print(f"{len(pending)} search cell(s) pending")

    total_leads = 0
    for cell in pending:
        label = cell["label"]
        query = f"tattoo shop in {label}"
        print(f"Searching: {query}")

        try:
            places = FAKE_PLACES_FOR_DRY_RUN if dry_run else places_client.search_text(query, api_key)
        except places_client.PlacesApiError as exc:
            print(f"  ERROR: {exc}")
            db.mark_cell_error(conn, label, str(exc), _now_iso())
            continue

        for place in places:
            lead = _place_to_lead(place, label)
            db.upsert_lead(conn, lead)
            total_leads += 1
            print(f"  [{lead['qualification_status']}] {lead['business_name']}")

            if not dry_run and lead["qualification_status"] == "qualified_outdated":
                try:
                    audit_result = site_audit.audit_site(lead["website_url"], psi_api_key)
                    db.update_lead_audit(
                        conn,
                        lead["google_place_id"],
                        audit_result["status"],
                        audit_result["score"],
                        audit_result["signals"],
                        audit_result["run_at"],
                    )
                    print(f"    audit: {audit_result['status']} (score={audit_result['score']})")
                except Exception as exc:
                    # Last line of defense: any unexpected failure in the audit
                    # path must not propagate out of run() and crash the batch --
                    # that would leave this cell's search un-marked-done and
                    # cause it to be re-searched (and re-billed) against the
                    # Places API on the next run.
                    db.update_lead_audit(
                        conn,
                        lead["google_place_id"],
                        "error",
                        None,
                        {"unexpected_error": str(exc)},
                        _now_iso(),
                    )
                    print(f"    audit: ERROR (unexpected: {exc})")

        db.mark_cell_done(conn, label, len(places), _now_iso())

    conn.close()
    print(f"\nDone. {total_leads} lead record(s) written to {db_path}")


def _place_to_lead(place: dict, search_cell: str) -> dict:
    website_url = place.get("websiteUri")
    has_website = bool(website_url)

    if not has_website:
        website_status = "none"
        qualification_status = "qualified_no_website"
        website_signals = {}
    else:
        result = site_check.check_website(website_url)
        website_status = result["status"]
        website_signals = result["signals"]
        qualification_status = site_check.qualification_for_status(website_status)

    return {
        "google_place_id": place["id"],
        "business_name": place.get("displayName", {}).get("text", "Unknown"),
        "formatted_address": place.get("formattedAddress"),
        "city": places_client.extract_address_component(place, "locality"),
        "state": places_client.extract_address_component(place, "administrative_area_level_1"),
        "zip": places_client.extract_address_component(place, "postal_code"),
        "phone": place.get("nationalPhoneNumber"),
        "website_url": website_url,
        "has_website": int(has_website),
        "website_status": website_status,
        "website_signals": website_signals,
        "qualification_status": qualification_status,
        "discovery_source": "google_places",
        "search_cell": search_cell,
        "discovered_at": _now_iso(),
        "raw_places_json": place,
    }


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Discovery Agent for tattoo shop leads")
    parser.add_argument("--db", default=DB_PATH_DEFAULT, help="SQLite db path (default: leads.db)")
    parser.add_argument("--limit-cities", type=int, default=None, help="Only search the first N seed cities")
    parser.add_argument("--state", default=None, help="Only search cities in this state (e.g. TX)")
    parser.add_argument("--dry-run", action="store_true", help="Use fake data, no real API calls")
    args = parser.parse_args()

    run(args.db, args.limit_cities, args.dry_run, args.state)


if __name__ == "__main__":
    main()
