import datetime
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

VALID_OUTCOMES = {"won", "lost", "no_response", "ongoing"}


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


def record_outcome(
    conn: sqlite3.Connection,
    lead_slug: str,
    business_name: str,
    outcome: str,
    closed_value: float | None = None,
    notes: str | None = None,
) -> None:
    """A lead's outcome can change over time (ongoing -> won, ongoing -> lost) --
    re-recording updates the existing row rather than erroring."""
    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"outcome must be one of {VALID_OUTCOMES}, got {outcome!r}")

    conn.execute(
        """
        INSERT INTO outcomes (lead_slug, business_name, outcome, closed_value, notes, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(lead_slug) DO UPDATE SET
            outcome = excluded.outcome,
            closed_value = excluded.closed_value,
            notes = excluded.notes,
            recorded_at = excluded.recorded_at
        """,
        (lead_slug, business_name, outcome, closed_value, notes,
         datetime.datetime.now(datetime.timezone.utc).isoformat()),
    )
    conn.commit()


def list_outcomes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM outcomes ORDER BY recorded_at DESC").fetchall()


def remove_outcome(conn: sqlite3.Connection, lead_slug: str) -> bool:
    """For correcting test/mistaken entries only."""
    cur = conn.execute("DELETE FROM outcomes WHERE lead_slug = ?", (lead_slug,))
    conn.commit()
    return cur.rowcount > 0
