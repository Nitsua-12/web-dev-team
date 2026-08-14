import tempfile
import unittest
from pathlib import Path

from deploy import build_root_robots_txt, find_indexable_html_outside_allowlist


class BuildRootRobotsTxtTests(unittest.TestCase):
    def test_no_indexable_slugs_disallows_everything(self):
        self.assertEqual(build_root_robots_txt(set()), "User-agent: *\nDisallow: /\n")

    def test_one_indexable_slug(self):
        result = build_root_robots_txt({"village-tattoo-nyc"})
        self.assertEqual(result, "User-agent: *\nDisallow: /\nAllow: /village-tattoo-nyc/\n")

    def test_multiple_indexable_slugs_sorted_for_determinism(self):
        result = build_root_robots_txt({"zzz-tattoo", "aaa-tattoo"})
        self.assertEqual(
            result,
            "User-agent: *\nDisallow: /\nAllow: /aaa-tattoo/\nAllow: /zzz-tattoo/\n",
        )


class FindIndexableHtmlOutsideAllowlistTests(unittest.TestCase):
    def test_no_violations_when_everything_noindex(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            slug_dir = output_dir / "some-tattoo-shop"
            slug_dir.mkdir()
            (slug_dir / "index.html").write_text(
                '<head><meta name="robots" content="noindex"></head>', encoding="utf-8"
            )
            self.assertEqual(find_indexable_html_outside_allowlist(output_dir, set()), [])

    def test_violation_detected_for_stale_index_follow_outside_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            slug_dir = output_dir / "village-tattoo-nyc-new-york"
            slug_dir.mkdir()
            html_file = slug_dir / "index.html"
            html_file.write_text(
                '<head><meta name="robots" content="index, follow"></head>', encoding="utf-8"
            )
            violations = find_indexable_html_outside_allowlist(output_dir, set())
            self.assertEqual(violations, [html_file])

    def test_slug_in_allowlist_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            slug_dir = output_dir / "village-tattoo-nyc-new-york"
            slug_dir.mkdir()
            (slug_dir / "index.html").write_text(
                '<head><meta name="robots" content="index, follow"></head>', encoding="utf-8"
            )
            violations = find_indexable_html_outside_allowlist(
                output_dir, {"village-tattoo-nyc-new-york"}
            )
            self.assertEqual(violations, [])

    def test_noindex_page_not_flagged_even_outside_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            slug_dir = output_dir / "some-other-shop"
            slug_dir.mkdir()
            (slug_dir / "index.html").write_text(
                '<head><meta name="robots" content="noindex"></head>', encoding="utf-8"
            )
            violations = find_indexable_html_outside_allowlist(output_dir, set())
            self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
