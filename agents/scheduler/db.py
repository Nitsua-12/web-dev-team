import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


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


def mark_sent(conn: sqlite3.Connection, lead_slug: str, business_name: str, channel: str, followup_index: int, sent_at: str) -> None:
    conn.execute(
        """
        INSERT INTO sends (lead_slug, business_name, channel, followup_index, sent_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(lead_slug, followup_index) DO UPDATE SET
            channel = excluded.channel,
            sent_at = excluded.sent_at
        """,
        (lead_slug, business_name, channel, followup_index, sent_at),
    )
    conn.commit()


def get_sends_for_lead(conn: sqlite3.Connection, lead_slug: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM sends WHERE lead_slug = ? ORDER BY followup_index", (lead_slug,)
    ).fetchall()


def get_all_leads_with_sends(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT lead_slug FROM sends").fetchall()
    return [r["lead_slug"] for r in rows]


def remove_send(conn: sqlite3.Connection, lead_slug: str, followup_index: int) -> bool:
    """For correcting test/mistaken entries only."""
    cur = conn.execute(
        "DELETE FROM sends WHERE lead_slug = ? AND followup_index = ?", (lead_slug, followup_index)
    )
    conn.commit()
    return cur.rowcount > 0
