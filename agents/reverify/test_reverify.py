import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import reverify

# Matches the real leads table (agents/discovery/schema.sql) including the
# website-audit columns added by agents/discovery/site_audit.py.
LEADS_SCHEMA = """
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
    has_website         INTEGER NOT NULL DEFAULT 0,
    website_status      TEXT NOT NULL DEFAULT 'unknown',
    website_signals     TEXT,
    qualification_status TEXT NOT NULL DEFAULT 'needs_review',
    discovery_source    TEXT NOT NULL DEFAULT 'google_places',
    search_cell         TEXT,
    discovered_at       TEXT NOT NULL,
    raw_places_json     TEXT,
    audit_status        TEXT NOT NULL DEFAULT 'not_run',
    audit_score         INTEGER,
    audit_signals       TEXT,
    audit_run_at        TEXT
);
"""


class ApplyLeadUpdateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db_path = tmp.name
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(LEADS_SCHEMA)
        self.conn.execute(
            """
            INSERT INTO leads (
                google_place_id, business_name, qualification_status, discovered_at,
                audit_status, audit_score, audit_signals, audit_run_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "place-1", "Old School Ink", "qualified_outdated", "2026-01-01T00:00:00Z",
                "ok", 42, json.dumps({"title": "Old School Ink"}), "2026-01-02T00:00:00Z",
            ),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        Path(self.db_path).unlink(missing_ok=True)

    def test_status_change_resets_audit_columns(self):
        reverify.apply_lead_update(
            self.conn, "place-1",
            new_url="https://oldschoolink.example.com",
            new_website_status="modern",
            new_qualification="disqualified_modern",
        )
        row = self.conn.execute("SELECT * FROM leads WHERE google_place_id = ?", ("place-1",)).fetchone()
        self.assertEqual(row["qualification_status"], "disqualified_modern")
        self.assertEqual(row["website_status"], "modern")
        self.assertEqual(row["website_url"], "https://oldschoolink.example.com")
        self.assertEqual(row["has_website"], 1)
        self.assertEqual(row["audit_status"], "not_run")
        self.assertIsNone(row["audit_score"])
        self.assertIsNone(row["audit_signals"])
        self.assertIsNone(row["audit_run_at"])

    def test_reverse_direction_also_resets(self):
        # disqualified_modern -> qualified_outdated: no audit exists yet for
        # this lead in this scenario, but confirm the reset path is safe to
        # run even when the columns are already at their default.
        self.conn.execute(
            "UPDATE leads SET qualification_status = 'disqualified_modern', "
            "audit_status = 'not_run', audit_score = NULL, audit_signals = NULL, audit_run_at = NULL "
            "WHERE google_place_id = ?",
            ("place-1",),
        )
        self.conn.commit()

        reverify.apply_lead_update(
            self.conn, "place-1",
            new_url="http://oldschoolink.example.com",
            new_website_status="outdated",
            new_qualification="qualified_outdated",
        )
        row = self.conn.execute("SELECT * FROM leads WHERE google_place_id = ?", ("place-1",)).fetchone()
        self.assertEqual(row["qualification_status"], "qualified_outdated")
        self.assertEqual(row["audit_status"], "not_run")
        self.assertIsNone(row["audit_score"])

    def test_apply_lead_update_after_discovery_migration_on_premigration_db(self):
        # reverify.py can run against a leads.db that never had
        # discovery_agent.py's own init_db() called on it (the two agents
        # write to the same file independently). Simulate that: a
        # pre-migration schema with no audit columns at all, then confirm
        # calling discovery_db.init_db() (as main() now does) makes
        # apply_lead_update work rather than crash with "no such column".
        premigration_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        premigration_tmp.close()
        premigration_path = premigration_tmp.name
        try:
            # Full real base schema (agents/discovery/schema.sql) as it was
            # before the 4 audit columns were added -- not a simplified
            # fixture, since discovery_db.init_db()'s CREATE TABLE IF NOT
            # EXISTS only skips table creation if one already exists; it
            # doesn't reconcile a mismatched one, so this has to match
            # reality for the test to mean anything.
            premigration_conn = sqlite3.connect(premigration_path)
            premigration_conn.executescript("""
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
                    has_website         INTEGER NOT NULL DEFAULT 0,
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
            """)
            premigration_conn.execute(
                "INSERT INTO leads (google_place_id, business_name, qualification_status, discovered_at) "
                "VALUES (?, ?, ?, ?)",
                ("place-2", "No Website Tattoo Co", "qualified_no_website", "2026-01-01T00:00:00Z"),
            )
            premigration_conn.commit()
            premigration_conn.close()

            reverify.discovery_db.init_db(premigration_path)

            conn = sqlite3.connect(premigration_path)
            conn.row_factory = sqlite3.Row
            reverify.apply_lead_update(
                conn, "place-2",
                new_url="https://newsite.example.com",
                new_website_status="outdated",
                new_qualification="qualified_outdated",
            )
            row = conn.execute("SELECT * FROM leads WHERE google_place_id = ?", ("place-2",)).fetchone()
            self.assertEqual(row["qualification_status"], "qualified_outdated")
            self.assertEqual(row["audit_status"], "not_run")
            conn.close()
        finally:
            Path(premigration_path).unlink(missing_ok=True)

    def test_no_website_sets_has_website_false(self):
        reverify.apply_lead_update(
            self.conn, "place-1",
            new_url=None,
            new_website_status="none",
            new_qualification="qualified_no_website",
        )
        row = self.conn.execute("SELECT * FROM leads WHERE google_place_id = ?", ("place-1",)).fetchone()
        self.assertEqual(row["has_website"], 0)
        self.assertIsNone(row["website_url"])
        self.assertEqual(row["audit_status"], "not_run")


if __name__ == "__main__":
    unittest.main()
