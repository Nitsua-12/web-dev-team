import tempfile
import unittest
from pathlib import Path

from generate_demo import read_indexable_slugs


class ReadIndexableSlugsTests(unittest.TestCase):
    def test_missing_file_returns_empty_set(self):
        missing = Path(tempfile.gettempdir()) / "definitely-does-not-exist-12345.txt"
        self.assertEqual(read_indexable_slugs(missing), set())

    def test_empty_file_returns_empty_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "indexable_slugs.txt"
            path.write_text("", encoding="utf-8")
            self.assertEqual(read_indexable_slugs(path), set())

    def test_populated_file_returns_slugs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "indexable_slugs.txt"
            path.write_text("village-tattoo-nyc\nink-and-iron-austin\n", encoding="utf-8")
            self.assertEqual(
                read_indexable_slugs(path),
                {"village-tattoo-nyc", "ink-and-iron-austin"},
            )

    def test_blank_lines_and_whitespace_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "indexable_slugs.txt"
            path.write_text("village-tattoo-nyc\n\n   \n  ink-and-iron-austin  \n", encoding="utf-8")
            self.assertEqual(
                read_indexable_slugs(path),
                {"village-tattoo-nyc", "ink-and-iron-austin"},
            )


if __name__ == "__main__":
    unittest.main()
