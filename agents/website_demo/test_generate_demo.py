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


from generate_demo import page_tokens, write_sitemap


class PageTokensRobotsTests(unittest.TestCase):
    def test_noindex_by_default(self):
        tokens = page_tokens("index.html", "some-slug", None, set())
        self.assertEqual(tokens["ROBOTS_META_TAG"], '<meta name="robots" content="noindex">')

    def test_index_follow_when_slug_cleared(self):
        tokens = page_tokens("index.html", "some-slug", None, {"some-slug"})
        self.assertEqual(tokens["ROBOTS_META_TAG"], '<meta name="robots" content="index, follow">')

    def test_other_slugs_not_cleared_by_a_different_slugs_clearance(self):
        tokens = page_tokens("index.html", "some-slug", None, {"a-different-slug"})
        self.assertEqual(tokens["ROBOTS_META_TAG"], '<meta name="robots" content="noindex">')

    def test_noindex_default_persists_even_with_site_base_url(self):
        tokens = page_tokens("index.html", "some-slug", "https://example.pages.dev", set())
        self.assertEqual(tokens["ROBOTS_META_TAG"], '<meta name="robots" content="noindex">')
        self.assertNotEqual(tokens["CANONICAL_TAG"], "")  # unaffected by the robots default


class PageTokensFaviconTests(unittest.TestCase):
    def test_favicon_href_is_absolute_and_slug_scoped(self):
        tokens = page_tokens("index.html", "some-slug", None, set())
        self.assertEqual(tokens["FAVICON_LINK"], '<link rel="icon" type="image/svg+xml" href="/some-slug/favicon.svg">')

    def test_favicon_href_same_regardless_of_page_depth(self):
        # Must resolve correctly from a page one level deeper than index.html
        # too (e.g. styles/custom-tattoos.html) -- an absolute path does,
        # a path relative to html_file wouldn't.
        shallow = page_tokens("index.html", "some-slug", None, set())
        deep = page_tokens("styles/custom-tattoos.html", "some-slug", None, set())
        self.assertEqual(shallow["FAVICON_LINK"], deep["FAVICON_LINK"])

    def test_favicon_href_present_with_site_base_url_too(self):
        tokens = page_tokens("index.html", "some-slug", "https://example.pages.dev", set())
        self.assertEqual(tokens["FAVICON_LINK"], '<link rel="icon" type="image/svg+xml" href="/some-slug/favicon.svg">')


class WriteSitemapTests(unittest.TestCase):
    def test_writes_sitemap_but_not_robots_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            write_sitemap(dest, "some-slug", "https://example.pages.dev")
            self.assertTrue((dest / "sitemap.xml").exists())
            self.assertFalse((dest / "robots.txt").exists())
            sitemap_content = (dest / "sitemap.xml").read_text(encoding="utf-8")
            self.assertIn("https://example.pages.dev/some-slug/", sitemap_content)


if __name__ == "__main__":
    unittest.main()
