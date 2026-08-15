import sqlite3
import tempfile
import unittest
from pathlib import Path

import outcomes_cli

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
        self.assertEqual(outcomes_cli.slugify("Ink & Iron Tattoo", "Austin"), "ink-iron-tattoo-austin")

    def test_empty_inputs_fall_back_to_lead(self):
        self.assertEqual(outcomes_cli.slugify("", ""), "lead")


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
        row = outcomes_cli.lookup_lead(self.db_path, "ink & iron tattoo", None)
        self.assertIsNotNone(row)
        self.assertEqual(row["business_name"], "Ink & Iron Tattoo")

    def test_lookup_by_business_name_no_match(self):
        self.assertIsNone(outcomes_cli.lookup_lead(self.db_path, "Nonexistent Shop", None))

    def test_lookup_by_phone_last_ten_digits_ignores_formatting(self):
        row = outcomes_cli.lookup_lead(self.db_path, None, "1-512-555-0100")
        self.assertIsNotNone(row)
        self.assertEqual(row["business_name"], "Ink & Iron Tattoo")

    def test_lookup_by_phone_no_match(self):
        self.assertIsNone(outcomes_cli.lookup_lead(self.db_path, None, "212-555-9999"))


if __name__ == "__main__":
    unittest.main()
