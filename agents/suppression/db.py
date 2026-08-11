import datetime
import re
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

VALID_REASONS = {"unsubscribe", "stop_reply", "manual", "bounce", "legal_request"}


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


def normalize_phone(phone: str) -> str | None:
    """Returns E.164 (+1XXXXXXXXXX) for a 10 or 11-digit US number, else None."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return None


def normalize_email(email: str) -> str | None:
    email = (email or "").strip().lower()
    return email or None


def normalize(contact_type: str, raw_value: str) -> str | None:
    if contact_type == "phone":
        return normalize_phone(raw_value)
    if contact_type == "email":
        return normalize_email(raw_value)
    raise ValueError(f"Unknown contact_type: {contact_type}")


def add_suppression(
    conn: sqlite3.Connection,
    contact_type: str,
    raw_value: str,
    reason: str,
    source: str | None = None,
    notes: str | None = None,
) -> str:
    """Normalizes and inserts a suppression. Returns the normalized value.
    Re-adding an existing entry updates reason/source/notes rather than erroring."""
    if reason not in VALID_REASONS:
        raise ValueError(f"reason must be one of {VALID_REASONS}, got {reason!r}")

    normalized = normalize(contact_type, raw_value)
    if not normalized:
        raise ValueError(f"Could not normalize {contact_type} value: {raw_value!r}")

    conn.execute(
        """
        INSERT INTO suppressions (contact_type, contact_value, reason, source, notes, added_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(contact_type, contact_value) DO UPDATE SET
            reason = excluded.reason,
            source = excluded.source,
            notes = excluded.notes
        """,
        (contact_type, normalized, reason, source, notes, datetime.datetime.now(datetime.timezone.utc).isoformat()),
    )
    conn.commit()
    return normalized


def is_suppressed(conn: sqlite3.Connection, contact_type: str, raw_value: str) -> bool:
    normalized = normalize(contact_type, raw_value)
    if not normalized:
        return False  # can't normalize -> can't have been suppressed under a normalized value
    row = conn.execute(
        "SELECT 1 FROM suppressions WHERE contact_type = ? AND contact_value = ?",
        (contact_type, normalized),
    ).fetchone()
    return row is not None


def list_suppressions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM suppressions ORDER BY added_at DESC").fetchall()


def remove_suppression(conn: sqlite3.Connection, contact_type: str, raw_value: str) -> bool:
    """For correcting mistaken entries only -- not for routine use. Returns True if a row was removed."""
    normalized = normalize(contact_type, raw_value)
    if not normalized:
        return False
    cur = conn.execute(
        "DELETE FROM suppressions WHERE contact_type = ? AND contact_value = ?",
        (contact_type, normalized),
    )
    conn.commit()
    return cur.rowcount > 0
