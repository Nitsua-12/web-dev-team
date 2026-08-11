import unittest
from unittest.mock import patch

import httpx

import site_audit


class OnPageSeoParserTests(unittest.TestCase):
    def test_extract_title_present(self):
        html = "<html><head><title>Old School Ink Tattoo Shop</title></head></html>"
        self.assertEqual(site_audit.extract_title(html), "Old School Ink Tattoo Shop")

    def test_extract_title_missing(self):
        self.assertIsNone(site_audit.extract_title("<html><head></head></html>"))

    def test_extract_meta_description_present(self):
        html = '<meta name="description" content="Best tattoo shop in Springfield">'
        self.assertEqual(site_audit.extract_meta_description(html), "Best tattoo shop in Springfield")

    def test_extract_meta_description_missing(self):
        self.assertIsNone(site_audit.extract_meta_description("<html></html>"))

    def test_count_h1_single(self):
        self.assertEqual(site_audit.count_h1("<h1>Welcome</h1><h2>Services</h2>"), 1)

    def test_count_h1_multiple(self):
        self.assertEqual(site_audit.count_h1("<h1>Welcome</h1><h1>Also Welcome</h1>"), 2)

    def test_count_h1_none(self):
        self.assertEqual(site_audit.count_h1("<h2>No H1 here</h2>"), 0)

    def test_heading_hierarchy_skip_detected(self):
        self.assertTrue(site_audit.has_heading_hierarchy_skip("<h1>Welcome</h1><h3>Services</h3>"))

    def test_heading_hierarchy_no_skip(self):
        html = "<h1>Welcome</h1><h2>Services</h2><h3>Tattoos</h3>"
        self.assertFalse(site_audit.has_heading_hierarchy_skip(html))

    def test_self_referencing_canonical_true(self):
        html = '<link rel="canonical" href="https://example.com/">'
        self.assertTrue(site_audit.has_self_referencing_canonical(html, "https://example.com/"))

    def test_self_referencing_canonical_false(self):
        html = '<link rel="canonical" href="https://other-domain.com/">'
        self.assertFalse(site_audit.has_self_referencing_canonical(html, "https://example.com/"))

    def test_self_referencing_canonical_missing(self):
        self.assertFalse(site_audit.has_self_referencing_canonical("<html></html>", "https://example.com/"))

    def test_noindex_detected(self):
        html = '<meta name="robots" content="noindex, nofollow">'
        self.assertTrue(site_audit.has_noindex_robots_meta(html))

    def test_noindex_absent(self):
        html = '<meta name="robots" content="index, follow">'
        self.assertFalse(site_audit.has_noindex_robots_meta(html))

    def test_json_ld_local_business_detected(self):
        html = '''<script type="application/ld+json">
        {"@context": "https://schema.org", "@type": "LocalBusiness", "name": "Old School Ink"}
        </script>'''
        self.assertTrue(site_audit.has_json_ld_local_business(html))

    def test_json_ld_absent(self):
        self.assertFalse(site_audit.has_json_ld_local_business("<html></html>"))

    def test_json_ld_malformed_does_not_crash(self):
        html = '<script type="application/ld+json">{not valid json</script>'
        self.assertFalse(site_audit.has_json_ld_local_business(html))

    def test_extract_phone_number_present(self):
        html = "<p>Call us at (217) 555-0100 today</p>"
        self.assertEqual(site_audit.extract_phone_number(html), "(217) 555-0100")

    def test_extract_phone_number_absent(self):
        self.assertIsNone(site_audit.extract_phone_number("<p>No phone here</p>"))

    def test_contact_form_detected(self):
        html = '<form action="/contact"><input type="email"></form>'
        self.assertTrue(site_audit.has_contact_form_or_booking_link(html))

    def test_contact_form_absent(self):
        self.assertFalse(site_audit.has_contact_form_or_booking_link("<html></html>"))

    def test_cta_detected(self):
        self.assertTrue(site_audit.has_cta('<a href="/book">Book Now</a>'))

    def test_cta_absent(self):
        self.assertFalse(site_audit.has_cta("<p>Welcome to our shop</p>"))


class FetchHomepageHtmlTests(unittest.TestCase):
    @patch("site_audit.site_check.robots_allow_fetch", return_value=True)
    def test_returns_html_on_success(self, _mock):
        def handler(request):
            return httpx.Response(200, text="<html>hi</html>")
        client = httpx.Client(transport=httpx.MockTransport(handler))
        html, error = site_audit.fetch_homepage_html("https://example.com", client=client)
        self.assertEqual(html, "<html>hi</html>")
        self.assertIsNone(error)

    @patch("site_audit.site_check.robots_allow_fetch", return_value=True)
    def test_returns_error_on_http_failure(self, _mock):
        def handler(request):
            raise httpx.ConnectTimeout("timed out", request=request)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        html, error = site_audit.fetch_homepage_html("https://example.com", client=client)
        self.assertIsNone(html)
        self.assertIsNotNone(error)

    @patch("site_audit.site_check.robots_allow_fetch", return_value=False)
    def test_respects_robots_disallow(self, _mock):
        html, error = site_audit.fetch_homepage_html("https://example.com")
        self.assertIsNone(html)
        self.assertEqual(error, "robots_disallowed")


class CheckUrlExistsTests(unittest.TestCase):
    def test_true_on_200(self):
        def handler(request):
            return httpx.Response(200)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.assertTrue(site_audit.check_url_exists("https://example.com/sitemap.xml", client=client))

    def test_false_on_404(self):
        def handler(request):
            return httpx.Response(404)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.assertFalse(site_audit.check_url_exists("https://example.com/sitemap.xml", client=client))

    def test_false_on_connection_error(self):
        def handler(request):
            raise httpx.ConnectError("refused", request=request)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.assertFalse(site_audit.check_url_exists("https://example.com/sitemap.xml", client=client))


if __name__ == "__main__":
    unittest.main()
