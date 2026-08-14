import unittest

from deploy import build_root_robots_txt


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


if __name__ == "__main__":
    unittest.main()
