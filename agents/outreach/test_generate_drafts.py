import tempfile
import unittest
from pathlib import Path

from generate_drafts import demo_url_for, demo_status_line


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


if __name__ == "__main__":
    unittest.main()
