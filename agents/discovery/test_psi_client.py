import unittest

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


if __name__ == "__main__":
    unittest.main()
