import datetime
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

VALID_STATUSES = {"approved", "rejected"}


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    finally:
        conn.close()


def record_decision(conn: sqlite3.Connection, lead_slug: str, business_name: str, status: str, notes: str | None = None) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES}, got {status!r}")
    conn.execute(
        """
        INSERT INTO approvals (lead_slug, business_name, status, notes, decided_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(lead_slug) DO UPDATE SET
            status = excluded.status,
            notes = excluded.notes,
            decided_at = excluded.decided_at
        """,
        (lead_slug, business_name, status, notes, datetime.datetime.now(datetime.timezone.utc).isoformat()),
    )
    conn.commit()


def get_decision(conn: sqlite3.Connection, lead_slug: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM approvals WHERE lead_slug = ?", (lead_slug,)).fetchone()


def list_decisions(conn: sqlite3.Connection, status: str | None = None) -> list[sqlite3.Row]:
    if status:
        return conn.execute("SELECT * FROM approvals WHERE status = ? ORDER BY decided_at DESC", (status,)).fetchall()
    return conn.execute("SELECT * FROM approvals ORDER BY decided_at DESC").fetchall()


def reset_decision(conn: sqlite3.Connection, lead_slug: str) -> bool:
    """Move a lead back to pending -- for correcting a mistaken decision."""
    cur = conn.execute("DELETE FROM approvals WHERE lead_slug = ?", (lead_slug,))
    conn.commit()
    return cur.rowcount > 0
