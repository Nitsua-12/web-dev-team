import sqlite3
import unittest

import db


class SchedulerDbTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE sends (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_slug       TEXT NOT NULL,
                business_name   TEXT NOT NULL,
                channel         TEXT NOT NULL CHECK(channel IN ('email', 'sms')),
                followup_index  INTEGER NOT NULL,
                sent_at         TEXT NOT NULL,
                UNIQUE(lead_slug, followup_index)
            );
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_mark_sent_inserts_row(self):
        db.mark_sent(self.conn, "ink-iron-austin", "Ink & Iron Tattoo", "email", 0, "2026-08-01")
        rows = db.get_sends_for_lead(self.conn, "ink-iron-austin")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["channel"], "email")
        self.assertEqual(rows[0]["sent_at"], "2026-08-01")

    def test_remarking_same_followup_updates_instead_of_erroring(self):
        db.mark_sent(self.conn, "ink-iron-austin", "Ink & Iron Tattoo", "email", 0, "2026-08-01")
        db.mark_sent(self.conn, "ink-iron-austin", "Ink & Iron Tattoo", "sms", 0, "2026-08-02")
        rows = db.get_sends_for_lead(self.conn, "ink-iron-austin")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["channel"], "sms")
        self.assertEqual(rows[0]["sent_at"], "2026-08-02")

    def test_get_sends_for_lead_ordered_by_followup_index(self):
        db.mark_sent(self.conn, "ink-iron-austin", "Ink & Iron Tattoo", "email", 1, "2026-08-10")
        db.mark_sent(self.conn, "ink-iron-austin", "Ink & Iron Tattoo", "email", 0, "2026-08-01")
        rows = db.get_sends_for_lead(self.conn, "ink-iron-austin")
        self.assertEqual([r["followup_index"] for r in rows], [0, 1])

    def test_get_sends_for_lead_empty_when_none(self):
        self.assertEqual(db.get_sends_for_lead(self.conn, "nonexistent"), [])

    def test_get_all_leads_with_sends_returns_distinct_slugs(self):
        db.mark_sent(self.conn, "shop-a", "Shop A", "email", 0, "2026-08-01")
        db.mark_sent(self.conn, "shop-a", "Shop A", "email", 1, "2026-08-05")
        db.mark_sent(self.conn, "shop-b", "Shop B", "sms", 0, "2026-08-01")
        slugs = db.get_all_leads_with_sends(self.conn)
        self.assertEqual(sorted(slugs), ["shop-a", "shop-b"])

    def test_remove_send_returns_true_when_removed(self):
        db.mark_sent(self.conn, "shop-a", "Shop A", "email", 0, "2026-08-01")
        self.assertTrue(db.remove_send(self.conn, "shop-a", 0))
        self.assertEqual(db.get_sends_for_lead(self.conn, "shop-a"), [])

    def test_remove_send_returns_false_when_no_match(self):
        self.assertFalse(db.remove_send(self.conn, "shop-a", 0))


if __name__ == "__main__":
    unittest.main()
