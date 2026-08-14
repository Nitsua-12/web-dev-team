import tempfile
import unittest
from pathlib import Path

from generate_dossier import demo_url_for, demo_status_line


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
        self.assertEqual(result, "no demo built yet")

    def test_demo_exists_not_hosted(self):
        result = demo_status_line(demo_exists=True, demo_url=None)
        self.assertEqual(result, "a concept demo has been built (not yet hosted/live)")

    def test_demo_live(self):
        result = demo_status_line(demo_exists=True, demo_url="https://example.pages.dev/ink-iron-tattoo-austin/")
        self.assertEqual(result, "a concept demo is live at https://example.pages.dev/ink-iron-tattoo-austin/")


if __name__ == "__main__":
    unittest.main()
