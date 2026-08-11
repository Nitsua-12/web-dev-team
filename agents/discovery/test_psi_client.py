import unittest
from unittest.mock import patch

import httpx

import psi_client

FIXTURE_WITH_FIELD_DATA = {
    "lighthouseResult": {
        "categories": {"performance": {"score": 0.42}},
        "audits": {
            "largest-contentful-paint": {"numericValue": 4123.5, "displayValue": "4.1 s"},
            "cumulative-layout-shift": {"numericValue": 0.15, "displayValue": "0.15"},
            "viewport": {"score": 1},
        },
    },
    "loadingExperience": {
        "metrics": {
            "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 4200, "category": "SLOW"},
            "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 12, "category": "AVERAGE"},
            "INTERACTION_TO_NEXT_PAINT": {"percentile": 300, "category": "AVERAGE"},
        }
    },
}

FIXTURE_WITHOUT_FIELD_DATA = {
    "lighthouseResult": {
        "categories": {"performance": {"score": 0.88}},
        "audits": {
            "largest-contentful-paint": {"numericValue": 1200.0, "displayValue": "1.2 s"},
            "cumulative-layout-shift": {"numericValue": 0.01, "displayValue": "0.01"},
            "viewport": {"score": 1},
        },
    },
    # no loadingExperience key at all -- realistic for a low-traffic small-business site
}


class ParsePagespeedResultTests(unittest.TestCase):
    def test_full_data(self):
        result = psi_client.parse_pagespeed_result(FIXTURE_WITH_FIELD_DATA)
        self.assertEqual(result["performance_score"], 42)
        self.assertEqual(result["lcp_ms"], 4123.5)
        self.assertEqual(result["cls"], 0.15)
        self.assertTrue(result["viewport_ok"])
        self.assertEqual(result["field_lcp_category"], "SLOW")
        self.assertEqual(result["field_cls_category"], "AVERAGE")
        self.assertEqual(result["field_inp_category"], "AVERAGE")
        self.assertTrue(result["has_field_data"])

    def test_no_field_data(self):
        result = psi_client.parse_pagespeed_result(FIXTURE_WITHOUT_FIELD_DATA)
        self.assertEqual(result["performance_score"], 88)
        self.assertFalse(result["has_field_data"])
        self.assertIsNone(result["field_lcp_category"])
        self.assertIsNone(result["field_cls_category"])
        self.assertIsNone(result["field_inp_category"])

    def test_missing_performance_category(self):
        result = psi_client.parse_pagespeed_result({"lighthouseResult": {"categories": {}, "audits": {}}})
        self.assertIsNone(result["performance_score"])
        self.assertIsNone(result["lcp_ms"])
        self.assertIsNone(result["viewport_ok"])


class RunPagespeedTests(unittest.TestCase):
    def test_returns_json_on_200(self):
        def handler(request):
            return httpx.Response(200, json={"lighthouseResult": {}})
        client = httpx.Client(transport=httpx.MockTransport(handler))
        result = psi_client.run_pagespeed("https://example.com", "fake-key", client=client)
        self.assertEqual(result, {"lighthouseResult": {}})

    @patch("psi_client.time.sleep")
    def test_retries_on_429_then_succeeds(self, _mock_sleep):
        calls = {"count": 0}

        def handler(request):
            calls["count"] += 1
            if calls["count"] < 3:
                return httpx.Response(429, text="rate limited")
            return httpx.Response(200, json={"ok": True})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        result = psi_client.run_pagespeed("https://example.com", "fake-key", max_retries=3, client=client)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls["count"], 3)

    @patch("psi_client.time.sleep")
    def test_raises_after_exhausting_retries(self, _mock_sleep):
        def handler(request):
            return httpx.Response(500, text="server error")
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with self.assertRaises(psi_client.PsiApiError):
            psi_client.run_pagespeed("https://example.com", "fake-key", max_retries=2, client=client)

    def test_raises_immediately_on_non_retryable_status(self):
        def handler(request):
            return httpx.Response(403, text="forbidden")
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with self.assertRaises(psi_client.PsiApiError):
            psi_client.run_pagespeed("https://example.com", "fake-key", max_retries=3, client=client)

    def test_raises_without_api_key(self):
        with self.assertRaises(psi_client.PsiApiError):
            psi_client.run_pagespeed("https://example.com", "")


if __name__ == "__main__":
    unittest.main()
