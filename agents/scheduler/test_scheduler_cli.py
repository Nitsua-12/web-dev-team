import datetime
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import scheduler_cli

LEADS_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    business_name TEXT NOT NULL,
    city          TEXT,
    phone         TEXT
);
"""

SUPPRESSIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS suppressions (
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


class SlugifyTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(scheduler_cli.slugify("Ink & Iron Tattoo", "Austin"), "ink-iron-tattoo-austin")

    def test_empty_inputs_fall_back_to_lead(self):
        self.assertEqual(scheduler_cli.slugify("", ""), "lead")


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
        row = scheduler_cli.lookup_lead(self.db_path, "ink & iron tattoo", None)
        self.assertIsNotNone(row)
        self.assertEqual(row["business_name"], "Ink & Iron Tattoo")

    def test_lookup_by_business_name_no_match(self):
        self.assertIsNone(scheduler_cli.lookup_lead(self.db_path, "Nonexistent Shop", None))

    def test_lookup_by_phone_last_ten_digits_ignores_formatting(self):
        row = scheduler_cli.lookup_lead(self.db_path, None, "1-512-555-0100")
        self.assertIsNotNone(row)
        self.assertEqual(row["business_name"], "Ink & Iron Tattoo")

    def test_lookup_by_phone_no_match(self):
        self.assertIsNone(scheduler_cli.lookup_lead(self.db_path, None, "212-555-9999"))


class ComputeScheduleTestCase(unittest.TestCase):
    """Shared fixture: a full temp environment for leads.db, sends.db,
    suppression.db, replies.db, and drafts/<slug>/draft.json, wired
    together via a SimpleNamespace standing in for argparse's Namespace
    (compute_schedule only ever reads attributes off it)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)

        self.leads_db = root / "leads.db"
        conn = sqlite3.connect(self.leads_db)
        conn.executescript(LEADS_SCHEMA)
        conn.commit()
        conn.close()

        self.sends_db = root / "sends.db"
        scheduler_cli.scheduler_db.init_db(str(self.sends_db))

        self.suppression_db = root / "suppression.db"
        conn = sqlite3.connect(self.suppression_db)
        conn.executescript(SUPPRESSIONS_SCHEMA)
        conn.commit()
        conn.close()

        self.replies_db = root / "replies.db"
        conn = sqlite3.connect(self.replies_db)
        conn.executescript(REPLIES_SCHEMA)
        conn.commit()
        conn.close()

        self.drafts_dir = root / "drafts"
        self.drafts_dir.mkdir()

        self.args = SimpleNamespace(
            leads_db=self.leads_db,
            suppression_db=self.suppression_db,
            replies_db=self.replies_db,
            sends_db=self.sends_db,
            drafts_dir=self.drafts_dir,
        )

    def add_lead(self, business_name, city="Austin", phone="512-555-0100"):
        conn = sqlite3.connect(self.leads_db)
        conn.execute("INSERT INTO leads (business_name, city, phone) VALUES (?, ?, ?)", (business_name, city, phone))
        conn.commit()
        conn.close()

    def add_draft(self, slug, followups):
        slug_dir = self.drafts_dir / slug
        slug_dir.mkdir()
        (slug_dir / "draft.json").write_text(json.dumps({"followups": followups}), encoding="utf-8")

    def mark_sent(self, slug, business_name, followup_index, sent_at):
        conn = scheduler_cli.scheduler_db.get_connection(str(self.sends_db))
        scheduler_cli.scheduler_db.mark_sent(conn, slug, business_name, "email", followup_index, sent_at)
        conn.close()

    def suppress_phone(self, phone):
        conn = scheduler_cli.suppression_db.get_connection(str(self.suppression_db))
        scheduler_cli.suppression_db.add_suppression(conn, "phone", phone, "manual")
        conn.close()

    def add_reply(self, slug, business_name):
        conn = scheduler_cli.reply_db.get_connection(str(self.replies_db))
        scheduler_cli.reply_db.add_reply(conn, slug, business_name, "sms", "Sure", "interested", "s", "flagged")
        conn.close()


DEFAULT_FOLLOWUPS = [
    {"day_offset": 4, "subject": "Following up"},
    {"day_offset": 16, "subject": "Last check-in"},
]


class ComputeScheduleTests(ComputeScheduleTestCase):
    def test_empty_when_no_sends(self):
        self.assertEqual(scheduler_cli.compute_schedule(self.args, datetime.date(2026, 8, 1)), [])

    def test_schedules_next_followup_after_initial_send(self):
        self.add_lead("Ink & Iron Tattoo")
        self.add_draft("ink-iron-tattoo-austin", DEFAULT_FOLLOWUPS)
        self.mark_sent("ink-iron-tattoo-austin", "Ink & Iron Tattoo", 0, "2026-08-01")

        rows = scheduler_cli.compute_schedule(self.args, datetime.date(2026, 8, 1))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["followup_index"], 1)
        self.assertEqual(rows[0]["due_date"], "2026-08-05")
        self.assertEqual(rows[0]["days_until_due"], 4)

    def test_overdue_followup_has_negative_days_until_due(self):
        self.add_lead("Ink & Iron Tattoo")
        self.add_draft("ink-iron-tattoo-austin", DEFAULT_FOLLOWUPS)
        self.mark_sent("ink-iron-tattoo-austin", "Ink & Iron Tattoo", 0, "2026-08-01")

        rows = scheduler_cli.compute_schedule(self.args, datetime.date(2026, 8, 10))
        self.assertEqual(rows[0]["days_until_due"], -5)

    def test_skips_lead_with_no_initial_send(self):
        # A followup logged without a followup_index=0 anchor -- shouldn't happen
        # in practice, but compute_schedule must not crash or fabricate a due date.
        self.add_lead("Ink & Iron Tattoo")
        self.add_draft("ink-iron-tattoo-austin", DEFAULT_FOLLOWUPS)
        self.mark_sent("ink-iron-tattoo-austin", "Ink & Iron Tattoo", 1, "2026-08-05")
        self.assertEqual(scheduler_cli.compute_schedule(self.args, datetime.date(2026, 8, 1)), [])

    def test_skips_suppressed_lead(self):
        self.add_lead("Ink & Iron Tattoo", phone="512-555-0100")
        self.add_draft("ink-iron-tattoo-austin", DEFAULT_FOLLOWUPS)
        self.mark_sent("ink-iron-tattoo-austin", "Ink & Iron Tattoo", 0, "2026-08-01")
        self.suppress_phone("512-555-0100")
        self.assertEqual(scheduler_cli.compute_schedule(self.args, datetime.date(2026, 8, 1)), [])

    def test_skips_lead_with_any_reply_logged(self):
        self.add_lead("Ink & Iron Tattoo")
        self.add_draft("ink-iron-tattoo-austin", DEFAULT_FOLLOWUPS)
        self.mark_sent("ink-iron-tattoo-austin", "Ink & Iron Tattoo", 0, "2026-08-01")
        self.add_reply("ink-iron-tattoo-austin", "Ink & Iron Tattoo")
        self.assertEqual(scheduler_cli.compute_schedule(self.args, datetime.date(2026, 8, 1)), [])

    def test_skips_lead_with_no_draft_json(self):
        self.add_lead("Ink & Iron Tattoo")
        self.mark_sent("ink-iron-tattoo-austin", "Ink & Iron Tattoo", 0, "2026-08-01")
        self.assertEqual(scheduler_cli.compute_schedule(self.args, datetime.date(2026, 8, 1)), [])

    def test_skips_lead_fully_followed_up(self):
        self.add_lead("Ink & Iron Tattoo")
        self.add_draft("ink-iron-tattoo-austin", DEFAULT_FOLLOWUPS)
        self.mark_sent("ink-iron-tattoo-austin", "Ink & Iron Tattoo", 0, "2026-08-01")
        self.mark_sent("ink-iron-tattoo-austin", "Ink & Iron Tattoo", 1, "2026-08-05")
        self.mark_sent("ink-iron-tattoo-austin", "Ink & Iron Tattoo", 2, "2026-08-17")
        self.assertEqual(scheduler_cli.compute_schedule(self.args, datetime.date(2026, 8, 20)), [])

    def test_multiple_leads_sorted_by_days_until_due(self):
        self.add_lead("Shop A", city="Austin", phone="512-555-0100")
        self.add_draft("shop-a-austin", DEFAULT_FOLLOWUPS)
        self.mark_sent("shop-a-austin", "Shop A", 0, "2026-08-01")  # due in 4 days

        self.add_lead("Shop B", city="Chicago", phone="312-555-0100")
        self.add_draft("shop-b-chicago", DEFAULT_FOLLOWUPS)
        self.mark_sent("shop-b-chicago", "Shop B", 0, "2026-07-20")  # already overdue

        rows = scheduler_cli.compute_schedule(self.args, datetime.date(2026, 8, 1))
        self.assertEqual([r["business_name"] for r in rows], ["Shop B", "Shop A"])


if __name__ == "__main__":
    unittest.main()
