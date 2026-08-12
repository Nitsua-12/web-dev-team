import unittest
from unittest.mock import patch

import httpx

import site_check


class CheckWebsiteStatusCodeTests(unittest.TestCase):
    """check_website() has no client-injection param (unlike site_audit.py's
    fetch helpers) since it's called by discovery_agent.py and reverify.py
    with a stable, unchanged signature -- so these tests patch httpx.get
    directly rather than injecting a MockTransport client."""

    @patch("site_check.robots_allow_fetch", return_value=True)
    @patch("site_check.httpx.get")
    def test_403_bot_block_returns_unknown_not_scored(self, mock_get, _mock_robots):
        mock_get.return_value = httpx.Response(
            403, text="<html>Access Denied</html>", request=httpx.Request("GET", "https://example.com")
        )
        result = site_check.check_website("https://example.com")
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["signals"]["fetch_error"], "http_403")

    @patch("site_check.robots_allow_fetch", return_value=True)
    @patch("site_check.httpx.get")
    def test_404_returns_unknown(self, mock_get, _mock_robots):
        mock_get.return_value = httpx.Response(
            404, text="Not Found", request=httpx.Request("GET", "https://example.com")
        )
        result = site_check.check_website("https://example.com")
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["signals"]["fetch_error"], "http_404")

    @patch("site_check.robots_allow_fetch", return_value=True)
    @patch("site_check.httpx.get")
    def test_500_returns_unknown(self, mock_get, _mock_robots):
        mock_get.return_value = httpx.Response(
            500, text="Server Error", request=httpx.Request("GET", "https://example.com")
        )
        result = site_check.check_website("https://example.com")
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["signals"]["fetch_error"], "http_500")

    @patch("site_check.robots_allow_fetch", return_value=True)
    @patch("site_check.httpx.get")
    def test_200_still_scores_normally(self, mock_get, _mock_robots):
        html = (
            "<html><head><title>Modern Shop</title>"
            '<meta name="viewport" content="width=device-width"></head>'
            "<body>&copy; 2026 Modern Shop</body></html>"
        )
        mock_get.return_value = httpx.Response(
            200, text=html, request=httpx.Request("GET", "https://example.com")
        )
        result = site_check.check_website("https://example.com")
        self.assertEqual(result["status"], "modern")
        self.assertNotIn("fetch_error", result["signals"])

    @patch("site_check.robots_allow_fetch", return_value=True)
    @patch("site_check.httpx.get")
    def test_200_outdated_site_still_scores_outdated(self, mock_get, _mock_robots):
        html = "<html><body>&copy; 2015 Old Shop -- best viewed in Internet Explorer</body></html>"
        mock_get.return_value = httpx.Response(
            200, text=html, request=httpx.Request("GET", "http://example.com")
        )
        result = site_check.check_website("http://example.com")
        self.assertEqual(result["status"], "outdated")
        self.assertNotIn("fetch_error", result["signals"])

    @patch("site_check.robots_allow_fetch", return_value=False)
    def test_robots_disallowed_still_returns_unknown(self, _mock_robots):
        result = site_check.check_website("https://example.com")
        self.assertEqual(result["status"], "unknown")
        self.assertTrue(result["signals"]["robots_disallowed"])


class QualificationForStatusTests(unittest.TestCase):
    def test_outdated_maps_to_qualified_outdated(self):
        self.assertEqual(site_check.qualification_for_status("outdated"), "qualified_outdated")

    def test_modern_maps_to_disqualified_modern(self):
        self.assertEqual(site_check.qualification_for_status("modern"), "disqualified_modern")

    def test_unknown_maps_to_needs_review(self):
        self.assertEqual(site_check.qualification_for_status("unknown"), "needs_review")

    def test_error_maps_to_needs_review(self):
        self.assertEqual(site_check.qualification_for_status("error"), "needs_review")

    def test_unrecognized_status_falls_back_to_needs_review(self):
        # Anything that isn't exactly "outdated" or "modern" is treated as
        # "don't guess" -- this is the same conservative default check_website()
        # itself uses for its own unknown/error statuses.
        self.assertEqual(site_check.qualification_for_status("something-new"), "needs_review")


if __name__ == "__main__":
    unittest.main()
