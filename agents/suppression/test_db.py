import sqlite3
import unittest

import db


class NormalizePhoneTests(unittest.TestCase):
    def test_ten_digit(self):
        self.assertEqual(db.normalize_phone("(212) 555-0100"), "+12125550100")

    def test_eleven_digit_leading_one(self):
        self.assertEqual(db.normalize_phone("1-212-555-0100"), "+12125550100")

    def test_too_short(self):
        self.assertIsNone(db.normalize_phone("5550100"))

    def test_eleven_digit_not_leading_one(self):
        self.assertIsNone(db.normalize_phone("22125550100"))

    def test_empty(self):
        self.assertIsNone(db.normalize_phone(""))

    def test_none(self):
        self.assertIsNone(db.normalize_phone(None))


class NormalizeEmailTests(unittest.TestCase):
    def test_lowercases_and_trims(self):
        self.assertEqual(db.normalize_email("  Jane@Shop.com  "), "jane@shop.com")

    def test_empty_is_none(self):
        self.assertIsNone(db.normalize_email(""))

    def test_none_is_none(self):
        self.assertIsNone(db.normalize_email(None))


class NormalizeDispatchTests(unittest.TestCase):
    def test_phone_dispatch(self):
        self.assertEqual(db.normalize("phone", "212-555-0100"), "+12125550100")

    def test_email_dispatch(self):
        self.assertEqual(db.normalize("email", "Jane@Shop.com"), "jane@shop.com")

    def test_unknown_contact_type_raises(self):
        with self.assertRaises(ValueError):
            db.normalize("carrier_pigeon", "whatever")


class SuppressionDbTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE suppressions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_type  TEXT NOT NULL CHECK(contact_type IN ('phone', 'email')),
                contact_value TEXT NOT NULL,
                reason        TEXT NOT NULL,
                source        TEXT,
                notes         TEXT,
                added_at      TEXT NOT NULL,
                UNIQUE(contact_type, contact_value)
            );
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_add_suppression_normalizes_and_returns_value(self):
        normalized = db.add_suppression(self.conn, "phone", "(212) 555-0100", "manual")
        self.assertEqual(normalized, "+12125550100")

    def test_add_suppression_invalid_reason_raises(self):
        with self.assertRaises(ValueError):
            db.add_suppression(self.conn, "phone", "212-555-0100", "because_i_said_so")

    def test_add_suppression_unnormalizable_value_raises(self):
        with self.assertRaises(ValueError):
            db.add_suppression(self.conn, "phone", "123", "manual")

    def test_readding_same_contact_updates_instead_of_erroring(self):
        db.add_suppression(self.conn, "phone", "212-555-0100", "manual", source="phone_call", notes="first")
        db.add_suppression(self.conn, "phone", "212-555-0100", "stop_reply", source="sms_reply", notes="second")
        rows = db.list_suppressions(self.conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "stop_reply")
        self.assertEqual(rows[0]["source"], "sms_reply")
        self.assertEqual(rows[0]["notes"], "second")

    def test_is_suppressed_true_after_add(self):
        db.add_suppression(self.conn, "email", "jane@shop.com", "unsubscribe")
        self.assertTrue(db.is_suppressed(self.conn, "email", "Jane@Shop.com "))

    def test_is_suppressed_false_when_absent(self):
        self.assertFalse(db.is_suppressed(self.conn, "phone", "212-555-0100"))

    def test_is_suppressed_false_for_unnormalizable_value(self):
        self.assertFalse(db.is_suppressed(self.conn, "phone", "123"))

    def test_list_suppressions_ordered_newest_first(self):
        db.add_suppression(self.conn, "phone", "212-555-0100", "manual")
        db.add_suppression(self.conn, "phone", "917-555-0199", "manual")
        rows = db.list_suppressions(self.conn)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["contact_value"], "+19175550199")
        self.assertEqual(rows[1]["contact_value"], "+12125550100")

    def test_remove_suppression_returns_true_when_removed(self):
        db.add_suppression(self.conn, "phone", "212-555-0100", "manual")
        self.assertTrue(db.remove_suppression(self.conn, "phone", "212-555-0100"))
        self.assertFalse(db.is_suppressed(self.conn, "phone", "212-555-0100"))

    def test_remove_suppression_returns_false_when_no_match(self):
        self.assertFalse(db.remove_suppression(self.conn, "phone", "212-555-0100"))

    def test_remove_suppression_unnormalizable_value_returns_false(self):
        self.assertFalse(db.remove_suppression(self.conn, "phone", "123"))


if __name__ == "__main__":
    unittest.main()
