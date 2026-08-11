import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import db

# Exact copy of schema.sql as it exists before this task's changes -- used
# to simulate the real, already-populated leads.db before migration.
PRE_MIGRATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_cells (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    label         TEXT UNIQUE NOT NULL,
    state         TEXT NOT NULL,
    lat           REAL NOT NULL,
    lng           REAL NOT NULL,
    radius_m      INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    result_count  INTEGER,
    run_at        TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS leads (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    google_place_id     TEXT UNIQUE NOT NULL,
    business_name       TEXT NOT NULL,
    formatted_address    TEXT,
    city                TEXT,
    state               TEXT,
    zip                 TEXT,
    phone               TEXT,
    website_url         TEXT,
    has_website          INTEGER NOT NULL DEFAULT 0,
    website_status      TEXT NOT NULL DEFAULT 'unknown',
    website_signals     TEXT,
    qualification_status TEXT NOT NULL DEFAULT 'needs_review',
    discovery_source    TEXT NOT NULL DEFAULT 'google_places',
    search_cell         TEXT,
    discovered_at       TEXT NOT NULL,
    raw_places_json     TEXT
);

CREATE INDEX IF NOT EXISTS idx_leads_qualification ON leads (qualification_status);
CREATE INDEX IF NOT EXISTS idx_leads_state ON leads (state);
"""


class MigrationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db_path = tmp.name

    def tearDown(self):
        Path(self.db_path).unlink(missing_ok=True)

    def test_migration_adds_columns_and_preserves_existing_rows(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(PRE_MIGRATION_SCHEMA)
        conn.execute(
            "INSERT INTO leads (google_place_id, business_name, qualification_status, discovered_at) "
            "VALUES (?, ?, ?, ?)",
            ("place-1", "Old School Ink", "qualified_outdated", "2026-01-01T00:00:00Z"),
        )
        conn.commit()
        conn.close()

        db.init_db(self.db_path)

        conn = db.get_connection(self.db_path)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(leads)").fetchall()}
        for expected in ("audit_status", "audit_score", "audit_signals", "audit_run_at"):
            self.assertIn(expected, columns)

        row = conn.execute("SELECT * FROM leads WHERE google_place_id = ?", ("place-1",)).fetchone()
        self.assertEqual(row["business_name"], "Old School Ink")
        self.assertEqual(row["audit_status"], "not_run")
        conn.close()

    def test_running_init_db_twice_is_safe(self):
        db.init_db(self.db_path)
        db.init_db(self.db_path)  # must not raise "duplicate column name"
        conn = db.get_connection(self.db_path)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(leads)").fetchall()}
        self.assertIn("audit_status", columns)
        conn.close()

    def test_update_lead_audit_writes_fields(self):
        db.init_db(self.db_path)
        conn = db.get_connection(self.db_path)
        conn.execute(
            "INSERT INTO leads (google_place_id, business_name, discovered_at) VALUES (?, ?, ?)",
            ("place-2", "Test Shop", "2026-01-01T00:00:00Z"),
        )
        conn.commit()

        db.update_lead_audit(conn, "place-2", "ok", 42, {"title": "Test"}, "2026-01-02T00:00:00Z")

        row = conn.execute("SELECT * FROM leads WHERE google_place_id = ?", ("place-2",)).fetchone()
        self.assertEqual(row["audit_status"], "ok")
        self.assertEqual(row["audit_score"], 42)
        self.assertEqual(json.loads(row["audit_signals"]), {"title": "Test"})
        self.assertEqual(row["audit_run_at"], "2026-01-02T00:00:00Z")
        conn.close()


if __name__ == "__main__":
    unittest.main()
