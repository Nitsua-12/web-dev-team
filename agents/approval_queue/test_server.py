import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server

SENDS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sends (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_slug       TEXT NOT NULL,
    business_name   TEXT NOT NULL,
    channel         TEXT NOT NULL CHECK(channel IN ('email', 'sms')),
    followup_index  INTEGER NOT NULL,
    sent_at         TEXT NOT NULL,
    UNIQUE(lead_slug, followup_index)
);
"""


class AlreadySentTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db_path = Path(tmp.name)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def test_false_when_sends_db_file_does_not_exist(self):
        missing_path = self.db_path.parent / "does-not-exist.db"
        with patch("server.SENDS_DB", missing_path):
            self.assertFalse(server.already_sent("some-lead"))

    def test_false_when_file_exists_but_sends_table_does_not(self):
        # Exactly the real-world bug: scheduler_cli.py has never been run,
        # so sends.db exists (SQLite creates it on connect) but has no
        # schema applied yet. This must not raise.
        conn = sqlite3.connect(self.db_path)
        conn.close()
        with patch("server.SENDS_DB", self.db_path):
            self.assertFalse(server.already_sent("some-lead"))

    def test_false_when_table_exists_but_no_matching_row(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(SENDS_SCHEMA)
        conn.commit()
        conn.close()
        with patch("server.SENDS_DB", self.db_path):
            self.assertFalse(server.already_sent("some-lead"))

    def test_true_when_initial_send_is_logged(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(SENDS_SCHEMA)
        conn.execute(
            "INSERT INTO sends (lead_slug, business_name, channel, followup_index, sent_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("some-lead", "Some Shop", "email", 0, "2026-08-01T00:00:00Z"),
        )
        conn.commit()
        conn.close()
        with patch("server.SENDS_DB", self.db_path):
            self.assertTrue(server.already_sent("some-lead"))

    def test_false_when_only_a_followup_is_logged_not_the_initial_send(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(SENDS_SCHEMA)
        conn.execute(
            "INSERT INTO sends (lead_slug, business_name, channel, followup_index, sent_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("some-lead", "Some Shop", "email", 1, "2026-08-05T00:00:00Z"),
        )
        conn.commit()
        conn.close()
        with patch("server.SENDS_DB", self.db_path):
            self.assertFalse(server.already_sent("some-lead"))


if __name__ == "__main__":
    unittest.main()
