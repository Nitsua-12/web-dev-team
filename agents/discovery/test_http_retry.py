import unittest
from unittest.mock import call, patch

import httpx

import http_retry


class FakeApiError(RuntimeError):
    pass


class RequestWithRetryTests(unittest.TestCase):
    def test_returns_response_on_200(self):
        calls = {"count": 0}

        def request_fn():
            calls["count"] += 1
            return httpx.Response(200, json={"ok": True})

        response = http_retry.request_with_retry(request_fn, FakeApiError, "Fake API")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls["count"], 1)

    @patch("http_retry.time.sleep")
    def test_retries_on_429_then_succeeds(self, _mock_sleep):
        calls = {"count": 0}

        def request_fn():
            calls["count"] += 1
            if calls["count"] < 3:
                return httpx.Response(429, text="rate limited")
            return httpx.Response(200, json={"ok": True})

        response = http_retry.request_with_retry(request_fn, FakeApiError, "Fake API", max_retries=3)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls["count"], 3)
        # Pins the 2**attempt backoff progression, not just that *a* sleep happened.
        _mock_sleep.assert_has_calls([call(1), call(2)])

    @patch("http_retry.time.sleep")
    def test_retries_on_500_502_503(self, _mock_sleep):
        for status in (500, 502, 503):
            calls = {"count": 0}

            def request_fn():
                calls["count"] += 1
                if calls["count"] < 2:
                    return httpx.Response(status, text="server error")
                return httpx.Response(200, json={"ok": True})

            response = http_retry.request_with_retry(request_fn, FakeApiError, "Fake API", max_retries=3)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(calls["count"], 2)

    @patch("http_retry.time.sleep")
    def test_raises_after_exhausting_retries(self, _mock_sleep):
        calls = {"count": 0}

        def request_fn():
            calls["count"] += 1
            return httpx.Response(500, text="server error")

        with self.assertRaises(FakeApiError):
            http_retry.request_with_retry(request_fn, FakeApiError, "Fake API", max_retries=2)
        self.assertEqual(calls["count"], 2)

    def test_raises_immediately_on_non_retryable_status(self):
        calls = {"count": 0}

        def request_fn():
            calls["count"] += 1
            return httpx.Response(403, text="forbidden")

        with self.assertRaises(FakeApiError):
            http_retry.request_with_retry(request_fn, FakeApiError, "Fake API", max_retries=3)
        self.assertEqual(calls["count"], 1)

    def test_raises_immediately_on_transport_failure_without_retrying(self):
        calls = {"count": 0}

        def request_fn():
            calls["count"] += 1
            raise httpx.ConnectError("connection refused")

        with self.assertRaises(FakeApiError):
            http_retry.request_with_retry(request_fn, FakeApiError, "Fake API", max_retries=3)
        self.assertEqual(calls["count"], 1)

    def test_error_message_includes_context_label(self):
        def request_fn():
            return httpx.Response(403, text="forbidden")

        with self.assertRaises(FakeApiError) as ctx:
            http_retry.request_with_retry(request_fn, FakeApiError, "Fake API", max_retries=1)
        self.assertIn("Fake API", str(ctx.exception))


class ParseJsonResponseTests(unittest.TestCase):
    def test_returns_parsed_json(self):
        response = httpx.Response(200, json={"ok": True})
        self.assertEqual(http_retry.parse_json_response(response, FakeApiError, "Fake API"), {"ok": True})

    def test_raises_on_invalid_json(self):
        response = httpx.Response(200, text="<html>not json</html>")
        with self.assertRaises(FakeApiError):
            http_retry.parse_json_response(response, FakeApiError, "Fake API")


if __name__ == "__main__":
    unittest.main()
