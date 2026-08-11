import json
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

AUDIT_COLUMNS = {
    "audit_status": "TEXT NOT NULL DEFAULT 'not_run'",
    "audit_score": "INTEGER",
    "audit_signals": "TEXT",
    "audit_run_at": "TEXT",
}


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate_audit_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(leads)").fetchall()}
    for column, definition in AUDIT_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {column} {definition}")
    conn.commit()


def init_db(db_path: str) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
        _migrate_audit_columns(conn)
    finally:
        conn.close()


def upsert_search_cell(conn: sqlite3.Connection, label: str, state: str, lat: float, lng: float, radius_m: int) -> None:
    conn.execute(
        """
        INSERT INTO search_cells (label, state, lat, lng, radius_m, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
        ON CONFLICT(label) DO NOTHING
        """,
        (label, state, lat, lng, radius_m),
    )
    conn.commit()


def get_pending_cells(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM search_cells WHERE status = 'pending'").fetchall()


def mark_cell_done(conn: sqlite3.Connection, label: str, result_count: int, run_at: str) -> None:
    conn.execute(
        "UPDATE search_cells SET status = 'done', result_count = ?, run_at = ? WHERE label = ?",
        (result_count, run_at, label),
    )
    conn.commit()


def mark_cell_error(conn: sqlite3.Connection, label: str, error_message: str, run_at: str) -> None:
    conn.execute(
        "UPDATE search_cells SET status = 'error', error_message = ?, run_at = ? WHERE label = ?",
        (error_message, run_at, label),
    )
    conn.commit()


def upsert_lead(conn: sqlite3.Connection, lead: dict) -> None:
    conn.execute(
        """
        INSERT INTO leads (
            google_place_id, business_name, formatted_address, city, state, zip, phone,
            website_url, has_website, website_status, website_signals, qualification_status,
            discovery_source, search_cell, discovered_at, raw_places_json
        ) VALUES (
            :google_place_id, :business_name, :formatted_address, :city, :state, :zip, :phone,
            :website_url, :has_website, :website_status, :website_signals, :qualification_status,
            :discovery_source, :search_cell, :discovered_at, :raw_places_json
        )
        ON CONFLICT(google_place_id) DO UPDATE SET
            business_name = excluded.business_name,
            formatted_address = excluded.formatted_address,
            website_url = excluded.website_url,
            has_website = excluded.has_website,
            website_status = excluded.website_status,
            website_signals = excluded.website_signals,
            qualification_status = excluded.qualification_status,
            raw_places_json = excluded.raw_places_json
        """,
        {**lead, "website_signals": json.dumps(lead.get("website_signals") or {}),
         "raw_places_json": json.dumps(lead.get("raw_places_json") or {})},
    )
    conn.commit()


def update_lead_audit(
    conn: sqlite3.Connection,
    google_place_id: str,
    audit_status: str,
    audit_score: int | None,
    audit_signals: dict,
    audit_run_at: str,
) -> None:
    conn.execute(
        """
        UPDATE leads
        SET audit_status = ?, audit_score = ?, audit_signals = ?, audit_run_at = ?
        WHERE google_place_id = ?
        """,
        (audit_status, audit_score, json.dumps(audit_signals or {}), audit_run_at, google_place_id),
    )
    conn.commit()
