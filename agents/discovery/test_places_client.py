import unittest
from unittest.mock import patch

import httpx

import places_client


class SearchTextTests(unittest.TestCase):
    def test_returns_places_from_single_page(self):
        def handler(request):
            return httpx.Response(200, json={"places": [{"id": "place-1"}, {"id": "place-2"}]})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        places = places_client.search_text("tattoo shop in Springfield", "fake-key", client=client)
        self.assertEqual([p["id"] for p in places], ["place-1", "place-2"])

    @patch("places_client.time.sleep")
    def test_follows_pagination_across_pages(self, _mock_sleep):
        calls = {"count": 0}

        def handler(request):
            calls["count"] += 1
            if calls["count"] == 1:
                return httpx.Response(200, json={"places": [{"id": "place-1"}], "nextPageToken": "token-2"})
            return httpx.Response(200, json={"places": [{"id": "place-2"}]})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        places = places_client.search_text("tattoo shop", "fake-key", client=client)
        self.assertEqual([p["id"] for p in places], ["place-1", "place-2"])
        self.assertEqual(calls["count"], 2)

    @patch("places_client.time.sleep")
    def test_stops_at_max_pages_even_with_more_tokens_available(self, _mock_sleep):
        def handler(request):
            return httpx.Response(200, json={"places": [{"id": "place-x"}], "nextPageToken": "always-more"})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        places = places_client.search_text("tattoo shop", "fake-key", max_pages=2, client=client)
        self.assertEqual(len(places), 2)

    def test_raises_without_api_key(self):
        with self.assertRaises(places_client.PlacesApiError):
            places_client.search_text("tattoo shop", "")


class GetPlaceDetailsTests(unittest.TestCase):
    def test_returns_json_on_200(self):
        def handler(request):
            return httpx.Response(200, json={"websiteUri": "https://example.com"})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        result = places_client.get_place_details("place-1", "fake-key", client=client)
        self.assertEqual(result, {"websiteUri": "https://example.com"})

    @patch("places_client.time.sleep")
    def test_retries_on_429_then_succeeds(self, _mock_sleep):
        calls = {"count": 0}

        def handler(request):
            calls["count"] += 1
            if calls["count"] < 3:
                return httpx.Response(429, text="rate limited")
            return httpx.Response(200, json={"websiteUri": None})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        result = places_client.get_place_details("place-1", "fake-key", max_retries=3, client=client)
        self.assertEqual(result, {"websiteUri": None})
        self.assertEqual(calls["count"], 3)

    def test_raises_places_api_error_on_transport_failure(self):
        def handler(request):
            raise httpx.ConnectError("connection refused", request=request)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with self.assertRaises(places_client.PlacesApiError):
            places_client.get_place_details("place-1", "fake-key", client=client)

    def test_raises_places_api_error_on_invalid_json(self):
        def handler(request):
            return httpx.Response(200, text="<html>not json</html>")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with self.assertRaises(places_client.PlacesApiError):
            places_client.get_place_details("place-1", "fake-key", client=client)

    def test_raises_without_api_key(self):
        with self.assertRaises(places_client.PlacesApiError):
            places_client.get_place_details("place-1", "")


class ExtractAddressComponentTests(unittest.TestCase):
    def test_extracts_matching_component(self):
        place = {
            "addressComponents": [
                {"types": ["locality"], "shortText": "Springfield"},
                {"types": ["administrative_area_level_1"], "shortText": "IL"},
            ]
        }
        self.assertEqual(places_client.extract_address_component(place, "locality"), "Springfield")
        self.assertEqual(places_client.extract_address_component(place, "administrative_area_level_1"), "IL")

    def test_returns_none_when_no_match(self):
        place = {"addressComponents": [{"types": ["locality"], "shortText": "Springfield"}]}
        self.assertIsNone(places_client.extract_address_component(place, "postal_code"))

    def test_returns_none_when_no_address_components(self):
        self.assertIsNone(places_client.extract_address_component({}, "locality"))

    def test_falls_back_to_long_text(self):
        place = {"addressComponents": [{"types": ["administrative_area_level_1"], "longText": "Illinois"}]}
        self.assertEqual(places_client.extract_address_component(place, "administrative_area_level_1"), "Illinois")


if __name__ == "__main__":
    unittest.main()
