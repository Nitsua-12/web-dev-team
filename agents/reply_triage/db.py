import datetime
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


def add_reply(
    conn: sqlite3.Connection,
    lead_slug: str,
    business_name: str,
    channel: str,
    raw_text: str,
    classification: str,
    summary: str,
    action_taken: str,
) -> None:
    conn.execute(
        """
        INSERT INTO replies (lead_slug, business_name, channel, raw_text, classification, summary, action_taken, received_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (lead_slug, business_name, channel, raw_text, classification, summary, action_taken,
         datetime.datetime.now(datetime.timezone.utc).isoformat()),
    )
    conn.commit()


def list_replies(conn: sqlite3.Connection, lead_slug: str | None = None) -> list[sqlite3.Row]:
    if lead_slug:
        return conn.execute("SELECT * FROM replies WHERE lead_slug = ? ORDER BY received_at DESC", (lead_slug,)).fetchall()
    return conn.execute("SELECT * FROM replies ORDER BY received_at DESC").fetchall()


def remove_reply(conn: sqlite3.Connection, reply_id: int) -> bool:
    """For correcting test/mistaken entries only."""
    cur = conn.execute("DELETE FROM replies WHERE id = ?", (reply_id,))
    conn.commit()
    return cur.rowcount > 0
