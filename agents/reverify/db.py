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


def log_check(
    conn: sqlite3.Connection,
    place_id: str,
    business_name: str,
    previous_status: str,
    new_status: str,
    previous_website_url: str | None,
    new_website_url: str | None,
    changed: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO reverify_log
            (place_id, business_name, previous_status, new_status, previous_website_url, new_website_url, changed, checked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (place_id, business_name, previous_status, new_status, previous_website_url, new_website_url,
         int(changed), datetime.datetime.now(datetime.timezone.utc).isoformat()),
    )
    conn.commit()


def get_last_checked(conn: sqlite3.Connection, place_id: str) -> str | None:
    row = conn.execute(
        "SELECT checked_at FROM reverify_log WHERE place_id = ? ORDER BY checked_at DESC LIMIT 1",
        (place_id,),
    ).fetchone()
    return row["checked_at"] if row else None
