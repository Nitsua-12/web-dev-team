import sqlite3
import tempfile
import unittest
from pathlib import Path

from generate_drafts import demo_url_for, demo_status_line, build_user_prompt


class DemoUrlForTests(unittest.TestCase):
    def test_no_folder_no_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            demo_dir = Path(tmp)
            result = demo_url_for("Ink & Iron Tattoo", "Austin", demo_dir, "https://example.pages.dev")
            self.assertIsNone(result)

    def test_folder_exists_no_base_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            demo_dir = Path(tmp)
            (demo_dir / "ink-iron-tattoo-austin").mkdir()
            result = demo_url_for("Ink & Iron Tattoo", "Austin", demo_dir, None)
            self.assertIsNone(result)

    def test_folder_exists_and_base_url_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            demo_dir = Path(tmp)
            (demo_dir / "ink-iron-tattoo-austin").mkdir()
            result = demo_url_for("Ink & Iron Tattoo", "Austin", demo_dir, "https://example.pages.dev")
            self.assertEqual(result, "https://example.pages.dev/ink-iron-tattoo-austin/")

    def test_base_url_trailing_slash_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            demo_dir = Path(tmp)
            (demo_dir / "ink-iron-tattoo-austin").mkdir()
            result = demo_url_for("Ink & Iron Tattoo", "Austin", demo_dir, "https://example.pages.dev/")
            self.assertEqual(result, "https://example.pages.dev/ink-iron-tattoo-austin/")


class DemoStatusLineTests(unittest.TestCase):
    def test_no_demo_at_all(self):
        result = demo_status_line(demo_exists=False, demo_url=None)
        self.assertEqual(result, "No concept demo has been built for this shop yet.")

    def test_demo_exists_not_hosted(self):
        result = demo_status_line(demo_exists=True, demo_url=None)
        self.assertEqual(
            result,
            "A concept demo has been built for this shop but isn't hosted/live yet -- do not include a link.",
        )

    def test_demo_live(self):
        result = demo_status_line(demo_exists=True, demo_url="https://example.pages.dev/ink-iron-tattoo-austin/")
        self.assertEqual(
            result,
            "A concept demo is live for this shop at https://example.pages.dev/ink-iron-tattoo-austin/ "
            "-- reference this exact URL in the email (and follow-ups) when inviting them to look.",
        )


class BuildUserPromptDemoStatusTests(unittest.TestCase):
    def test_demo_status_line_appears_in_prompt(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE leads (business_name TEXT, city TEXT, state TEXT, "
            "phone TEXT, qualification_status TEXT, website_url TEXT, website_signals TEXT)"
        )
        conn.execute(
            "INSERT INTO leads VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Ink & Iron Tattoo", "Austin", "TX", "(512) 555-0100", "qualified_no_website", None, None),
        )
        lead = conn.execute("SELECT * FROM leads").fetchone()

        prompt = build_user_prompt(lead, demo_exists=True, demo_url="https://example.pages.dev/ink-iron-tattoo-austin/")
        self.assertIn(
            "A concept demo is live for this shop at https://example.pages.dev/ink-iron-tattoo-austin/",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
