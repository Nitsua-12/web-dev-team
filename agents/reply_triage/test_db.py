import sqlite3
import unittest

import db


class ReplyDbTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE replies (
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
        )

    def tearDown(self):
        self.conn.close()

    def test_add_reply_then_list_all(self):
        db.add_reply(
            self.conn, "ink-iron-austin", "Ink & Iron Tattoo", "sms", "Reply STOP",
            "opt_out", "Asked to stop contact.", "added to suppression list",
        )
        rows = db.list_replies(self.conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["lead_slug"], "ink-iron-austin")
        self.assertEqual(rows[0]["classification"], "opt_out")

    def test_list_replies_filtered_by_slug(self):
        db.add_reply(self.conn, "shop-a", "Shop A", "sms", "STOP", "opt_out", "s", "a")
        db.add_reply(self.conn, "shop-b", "Shop B", "email", "Sure!", "interested", "s", "a")
        rows = db.list_replies(self.conn, lead_slug="shop-b")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["business_name"], "Shop B")

    def test_list_replies_ordered_newest_first(self):
        db.add_reply(self.conn, "shop-a", "Shop A", "sms", "first", "unclear", "s", "a")
        db.add_reply(self.conn, "shop-a", "Shop A", "sms", "second", "unclear", "s", "a")
        rows = db.list_replies(self.conn, lead_slug="shop-a")
        self.assertEqual(rows[0]["raw_text"], "second")
        self.assertEqual(rows[1]["raw_text"], "first")

    def test_remove_reply_returns_true_when_removed(self):
        db.add_reply(self.conn, "shop-a", "Shop A", "sms", "STOP", "opt_out", "s", "a")
        reply_id = db.list_replies(self.conn)[0]["id"]
        self.assertTrue(db.remove_reply(self.conn, reply_id))
        self.assertEqual(db.list_replies(self.conn), [])

    def test_remove_reply_returns_false_when_no_match(self):
        self.assertFalse(db.remove_reply(self.conn, 999))


if __name__ == "__main__":
    unittest.main()
