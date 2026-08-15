import sqlite3
import tempfile
import unittest
from pathlib import Path

import stats

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

REPLIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS replies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_slug       TEXT NOT NULL,
    business_name   TEXT NOT NULL,
    channel         TEXT NOT NULL CHECK(channel IN ('email', 'sms', 'phone_call')),
    raw_text        TEXT NOT NULL,
    classification  TEXT NOT NULL,
    summary         TEXT,
    action_taken    TEXT,
    received_at     TEXT NOT NULL
);
"""

OUTCOMES_SCHEMA = """
CREATE TABLE IF NOT EXISTS outcomes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_slug     TEXT NOT NULL,
    business_name TEXT NOT NULL,
    outcome       TEXT NOT NULL CHECK(outcome IN ('won', 'lost', 'no_response', 'ongoing')),
    closed_value  REAL,
    notes         TEXT,
    recorded_at   TEXT NOT NULL,
    UNIQUE(lead_slug)
);
"""


class ComputeFunnelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sends_db = self.root / "sends.db"
        self.replies_db = self.root / "replies.db"
        self.outcomes_db = self.root / "outcomes.db"

    def _init(self, db_path, schema):
        conn = sqlite3.connect(db_path)
        conn.executescript(schema)
        conn.commit()
        conn.close()

    def test_all_sources_missing_returns_zeros_without_crashing(self):
        result = stats.compute_funnel(self.sends_db, self.replies_db, self.outcomes_db)
        self.assertEqual(result["total_sent"], 0)
        self.assertEqual(result["total_replied"], 0)
        self.assertEqual(result["reply_breakdown"], {})
        self.assertEqual(result["total_outcomes_recorded"], 0)
        self.assertEqual(result["outcome_breakdown"], {})
        self.assertIsNone(result["avg_won_value"])
        self.assertFalse(result["reply_sample_meaningful"])
        self.assertFalse(result["outcome_sample_meaningful"])

    def test_db_file_exists_but_schema_never_applied(self):
        # Exactly the real-world case a sibling agent's CLI has never been
        # run: sqlite3.connect() creates an empty file with no tables.
        for path in (self.sends_db, self.replies_db, self.outcomes_db):
            sqlite3.connect(path).close()
        result = stats.compute_funnel(self.sends_db, self.replies_db, self.outcomes_db)
        self.assertEqual(result["total_sent"], 0)
        self.assertEqual(result["total_replied"], 0)
        self.assertEqual(result["total_outcomes_recorded"], 0)

    def test_total_sent_counts_only_initial_sends_distinct_by_lead(self):
        self._init(self.sends_db, SENDS_SCHEMA)
        conn = sqlite3.connect(self.sends_db)
        conn.executemany(
            "INSERT INTO sends (lead_slug, business_name, channel, followup_index, sent_at) VALUES (?, ?, ?, ?, ?)",
            [
                ("shop-a", "Shop A", "email", 0, "2026-08-01"),
                ("shop-a", "Shop A", "email", 1, "2026-08-05"),  # a followup, not a new initial send
                ("shop-b", "Shop B", "sms", 0, "2026-08-02"),
            ],
        )
        conn.commit()
        conn.close()
        result = stats.compute_funnel(self.sends_db, self.replies_db, self.outcomes_db)
        self.assertEqual(result["total_sent"], 2)

    def test_reply_breakdown_and_total_replied(self):
        self._init(self.replies_db, REPLIES_SCHEMA)
        conn = sqlite3.connect(self.replies_db)
        conn.executemany(
            "INSERT INTO replies (lead_slug, business_name, channel, raw_text, classification, summary, action_taken, received_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("shop-a", "Shop A", "sms", "STOP", "opt_out", "s", "a", "2026-08-01"),
                ("shop-b", "Shop B", "email", "Sure!", "interested", "s", "a", "2026-08-02"),
                ("shop-c", "Shop C", "email", "Sure!", "interested", "s", "a", "2026-08-03"),
            ],
        )
        conn.commit()
        conn.close()
        result = stats.compute_funnel(self.sends_db, self.replies_db, self.outcomes_db)
        self.assertEqual(result["total_replied"], 3)
        self.assertEqual(result["reply_breakdown"], {"opt_out": 1, "interested": 2})

    def test_outcome_breakdown_and_avg_won_value_excludes_null(self):
        self._init(self.outcomes_db, OUTCOMES_SCHEMA)
        conn = sqlite3.connect(self.outcomes_db)
        conn.executemany(
            "INSERT INTO outcomes (lead_slug, business_name, outcome, closed_value, notes, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("shop-a", "Shop A", "won", 400.0, None, "2026-08-01"),
                ("shop-b", "Shop B", "won", 600.0, None, "2026-08-02"),
                ("shop-c", "Shop C", "lost", None, None, "2026-08-03"),
                ("shop-d", "Shop D", "ongoing", None, None, "2026-08-04"),
            ],
        )
        conn.commit()
        conn.close()
        result = stats.compute_funnel(self.sends_db, self.replies_db, self.outcomes_db)
        self.assertEqual(result["total_outcomes_recorded"], 4)
        self.assertEqual(result["outcome_breakdown"], {"won": 2, "lost": 1, "ongoing": 1})
        self.assertEqual(result["won_count"], 2)
        self.assertEqual(result["avg_won_value"], 500.0)

    def test_sample_meaningful_thresholds(self):
        self._init(self.sends_db, SENDS_SCHEMA)
        self._init(self.outcomes_db, OUTCOMES_SCHEMA)
        sends_conn = sqlite3.connect(self.sends_db)
        sends_conn.executemany(
            "INSERT INTO sends (lead_slug, business_name, channel, followup_index, sent_at) VALUES (?, ?, ?, ?, ?)",
            [(f"shop-{i}", f"Shop {i}", "email", 0, "2026-08-01") for i in range(4)],
        )
        sends_conn.commit()
        sends_conn.close()

        outcomes_conn = sqlite3.connect(self.outcomes_db)
        outcomes_conn.executemany(
            "INSERT INTO outcomes (lead_slug, business_name, outcome, closed_value, notes, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
            [(f"shop-{i}", f"Shop {i}", "lost", None, None, "2026-08-01") for i in range(4)],
        )
        outcomes_conn.commit()
        outcomes_conn.close()

        result = stats.compute_funnel(self.sends_db, self.replies_db, self.outcomes_db)
        # 4 sends, 4 outcomes -- both below MEANINGFUL_SAMPLE_SIZE (5)
        self.assertFalse(result["reply_sample_meaningful"])
        self.assertFalse(result["outcome_sample_meaningful"])

        # one more of each crosses the threshold
        sends_conn = sqlite3.connect(self.sends_db)
        sends_conn.execute(
            "INSERT INTO sends (lead_slug, business_name, channel, followup_index, sent_at) VALUES (?, ?, ?, ?, ?)",
            ("shop-4", "Shop 4", "email", 0, "2026-08-01"),
        )
        sends_conn.commit()
        sends_conn.close()

        outcomes_conn = sqlite3.connect(self.outcomes_db)
        outcomes_conn.execute(
            "INSERT INTO outcomes (lead_slug, business_name, outcome, closed_value, notes, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("shop-4", "Shop 4", "lost", None, None, "2026-08-01"),
        )
        outcomes_conn.commit()
        outcomes_conn.close()

        result = stats.compute_funnel(self.sends_db, self.replies_db, self.outcomes_db)
        self.assertTrue(result["reply_sample_meaningful"])
        self.assertTrue(result["outcome_sample_meaningful"])


if __name__ == "__main__":
    unittest.main()
