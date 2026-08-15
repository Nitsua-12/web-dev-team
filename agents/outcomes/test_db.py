import sqlite3
import unittest

import db


class OutcomesDbTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE outcomes (
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
        )

    def tearDown(self):
        self.conn.close()

    def test_record_outcome_inserts_row(self):
        db.record_outcome(self.conn, "ink-iron-austin", "Ink & Iron Tattoo", "won", closed_value=450.0, notes="Signed")
        rows = db.list_outcomes(self.conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "won")
        self.assertEqual(rows[0]["closed_value"], 450.0)

    def test_invalid_outcome_raises(self):
        with self.assertRaises(ValueError):
            db.record_outcome(self.conn, "ink-iron-austin", "Ink & Iron Tattoo", "maybe_later")

    def test_rerecording_outcome_updates_instead_of_erroring(self):
        db.record_outcome(self.conn, "ink-iron-austin", "Ink & Iron Tattoo", "ongoing", notes="Still talking")
        db.record_outcome(self.conn, "ink-iron-austin", "Ink & Iron Tattoo", "won", closed_value=450.0, notes="Signed")
        rows = db.list_outcomes(self.conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "won")
        self.assertEqual(rows[0]["closed_value"], 450.0)
        self.assertEqual(rows[0]["notes"], "Signed")

    def test_list_outcomes_ordered_newest_first(self):
        db.record_outcome(self.conn, "shop-a", "Shop A", "lost")
        db.record_outcome(self.conn, "shop-b", "Shop B", "won", closed_value=300.0)
        rows = db.list_outcomes(self.conn)
        self.assertEqual(rows[0]["lead_slug"], "shop-b")
        self.assertEqual(rows[1]["lead_slug"], "shop-a")

    def test_remove_outcome_returns_true_when_removed(self):
        db.record_outcome(self.conn, "shop-a", "Shop A", "lost")
        self.assertTrue(db.remove_outcome(self.conn, "shop-a"))
        self.assertEqual(db.list_outcomes(self.conn), [])

    def test_remove_outcome_returns_false_when_no_match(self):
        self.assertFalse(db.remove_outcome(self.conn, "shop-a"))


if __name__ == "__main__":
    unittest.main()
