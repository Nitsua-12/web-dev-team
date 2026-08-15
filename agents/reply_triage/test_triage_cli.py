import sqlite3
import tempfile
import unittest
from pathlib import Path

import triage_cli

# Matches the columns triage_cli.lookup_lead() actually reads
# (agents/discovery/schema.sql), trimmed to what's needed here.
LEADS_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    business_name TEXT NOT NULL,
    city          TEXT,
    phone         TEXT
);
"""


class SlugifyTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(triage_cli.slugify("Ink & Iron Tattoo", "Austin"), "ink-iron-tattoo-austin")

    def test_strips_leading_trailing_dashes(self):
        self.assertEqual(triage_cli.slugify("!!!Ink!!!", "Austin"), "ink-austin")

    def test_empty_inputs_fall_back_to_lead(self):
        self.assertEqual(triage_cli.slugify("", ""), "lead")


class LookupLeadTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db_path = Path(tmp.name)
        conn = sqlite3.connect(self.db_path)
        conn.executescript(LEADS_SCHEMA)
        conn.execute(
            "INSERT INTO leads (business_name, city, phone) VALUES (?, ?, ?)",
            ("Ink & Iron Tattoo", "Austin", "(512) 555-0100"),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def test_lookup_by_business_name_case_insensitive(self):
        row = triage_cli.lookup_lead(self.db_path, "ink & iron tattoo", None)
        self.assertIsNotNone(row)
        self.assertEqual(row["business_name"], "Ink & Iron Tattoo")

    def test_lookup_by_business_name_no_match(self):
        row = triage_cli.lookup_lead(self.db_path, "Nonexistent Shop", None)
        self.assertIsNone(row)

    def test_lookup_by_phone_last_ten_digits_ignores_formatting(self):
        row = triage_cli.lookup_lead(self.db_path, None, "1-512-555-0100")
        self.assertIsNotNone(row)
        self.assertEqual(row["business_name"], "Ink & Iron Tattoo")

    def test_lookup_by_phone_no_match(self):
        row = triage_cli.lookup_lead(self.db_path, None, "212-555-9999")
        self.assertIsNone(row)


class TakeActionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db_path = tmp.name
        triage_cli.suppression_db.init_db(self.db_path)
        self.conn = triage_cli.suppression_db.get_connection(self.db_path)

    def tearDown(self):
        self.conn.close()
        Path(self.db_path).unlink(missing_ok=True)

    def test_opt_out_with_phone_suppresses_via_sms(self):
        lead = {"phone": "212-555-0100"}
        action = triage_cli.take_action(lead, "sms", "opt_out", self.conn)
        self.assertIn("stop_reply", action)
        self.assertTrue(triage_cli.suppression_db.is_suppressed(self.conn, "phone", "212-555-0100"))

    def test_opt_out_with_phone_suppresses_via_email(self):
        lead = {"phone": "212-555-0100"}
        action = triage_cli.take_action(lead, "email", "opt_out", self.conn)
        self.assertIn("unsubscribe", action)
        self.assertTrue(triage_cli.suppression_db.is_suppressed(self.conn, "phone", "212-555-0100"))

    def test_opt_out_without_phone_does_not_suppress(self):
        lead = {"phone": None}
        action = triage_cli.take_action(lead, "sms", "opt_out", self.conn)
        self.assertIn("could not suppress", action)

    def test_interested_does_not_suppress(self):
        lead = {"phone": "212-555-0100"}
        triage_cli.take_action(lead, "email", "interested", self.conn)
        self.assertFalse(triage_cli.suppression_db.is_suppressed(self.conn, "phone", "212-555-0100"))

    def test_not_interested_does_not_suppress(self):
        lead = {"phone": "212-555-0100"}
        action = triage_cli.take_action(lead, "email", "not_interested", self.conn)
        self.assertIn("not auto-suppressed", action)
        self.assertFalse(triage_cli.suppression_db.is_suppressed(self.conn, "phone", "212-555-0100"))

    def test_question_flags_for_human(self):
        lead = {"phone": "212-555-0100"}
        action = triage_cli.take_action(lead, "email", "question", self.conn)
        self.assertIn("needs a human answer", action)

    def test_unclear_flags_for_review(self):
        lead = {"phone": "212-555-0100"}
        action = triage_cli.take_action(lead, "email", "unclear", self.conn)
        self.assertIn("unclear", action)


class UpdateDossierTests(unittest.TestCase):
    def test_missing_dossier_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            dossier_path = Path(tmp) / "dossier.md"
            result = triage_cli.update_dossier(dossier_path, "Ink & Iron", "sms", "STOP", "opt_out", "Asked to stop.")
            self.assertFalse(result)

    def test_inserts_after_marker_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            dossier_path = Path(tmp) / "dossier.md"
            dossier_path.write_text(
                "# Dossier\n\n**For internal use by the human salesperson only.**\n\n## Notes\nExisting content.\n",
                encoding="utf-8",
            )
            result = triage_cli.update_dossier(dossier_path, "Ink & Iron", "sms", "STOP", "opt_out", "Asked to stop.")
            self.assertTrue(result)
            updated = dossier_path.read_text(encoding="utf-8")
            self.assertIn("NEW REPLY -- ACTION NEEDED", updated)
            self.assertIn("Existing content.", updated)
            marker_idx = updated.index("**For internal use")
            flag_idx = updated.index("NEW REPLY")
            self.assertLess(marker_idx, flag_idx)

    def test_no_marker_prepends_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            dossier_path = Path(tmp) / "dossier.md"
            dossier_path.write_text("# Dossier\n\nNo marker here.\n", encoding="utf-8")
            triage_cli.update_dossier(dossier_path, "Ink & Iron", "email", "Sure!", "interested", "Wants to see it.")
            updated = dossier_path.read_text(encoding="utf-8")
            self.assertTrue(updated.startswith("\n## NEW REPLY"))
            self.assertIn("No marker here.", updated)


if __name__ == "__main__":
    unittest.main()
