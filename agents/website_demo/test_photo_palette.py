import io
import unittest

import httpx
from PIL import Image

import photo_palette


def _make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _solid_color_jpeg_bytes(rgb: tuple[int, int, int]) -> bytes:
    img = Image.new("RGB", (10, 10), rgb)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


PHOTO_NAME = "places/abc123/photos/xyz789"


class GetFirstPhotoNameTests(unittest.TestCase):
    def test_returns_first_photo_name(self):
        def handler(request):
            return httpx.Response(200, json={"photos": [{"name": PHOTO_NAME}, {"name": "places/other"}]})

        with _make_client(handler) as client:
            self.assertEqual(photo_palette._get_first_photo_name("place-1", "key", client), PHOTO_NAME)

    def test_empty_photos_array_returns_none(self):
        def handler(request):
            return httpx.Response(200, json={"photos": []})

        with _make_client(handler) as client:
            self.assertIsNone(photo_palette._get_first_photo_name("place-1", "key", client))

    def test_missing_photos_key_returns_none(self):
        def handler(request):
            return httpx.Response(200, json={})

        with _make_client(handler) as client:
            self.assertIsNone(photo_palette._get_first_photo_name("place-1", "key", client))

    def test_http_error_returns_none(self):
        def handler(request):
            return httpx.Response(403, text="forbidden")

        with _make_client(handler) as client:
            self.assertIsNone(photo_palette._get_first_photo_name("place-1", "key", client))

    def test_malformed_json_returns_none_instead_of_crashing(self):
        def handler(request):
            return httpx.Response(200, text="<html>not json</html>")

        with _make_client(handler) as client:
            self.assertIsNone(photo_palette._get_first_photo_name("place-1", "key", client))

    def test_field_mask_header_is_photos(self):
        captured = {}

        def handler(request):
            captured["field_mask"] = request.headers.get("X-Goog-FieldMask")
            return httpx.Response(200, json={"photos": []})

        with _make_client(handler) as client:
            photo_palette._get_first_photo_name("place-1", "key", client)
        self.assertEqual(captured["field_mask"], "photos")


class FetchPhotoBytesTests(unittest.TestCase):
    def test_returns_response_content(self):
        def handler(request):
            return httpx.Response(200, content=b"fake-jpeg-bytes")

        with _make_client(handler) as client:
            self.assertEqual(photo_palette._fetch_photo_bytes(PHOTO_NAME, "key", client), b"fake-jpeg-bytes")

    def test_http_error_returns_none(self):
        def handler(request):
            return httpx.Response(404, text="not found")

        with _make_client(handler) as client:
            self.assertIsNone(photo_palette._fetch_photo_bytes(PHOTO_NAME, "key", client))


class DominantAccentColorTests(unittest.TestCase):
    def test_picks_saturated_color_over_desaturated(self):
        # A solid, well-saturated mid-tone blue should pass the
        # saturation/value thresholds and be returned as-is.
        image_bytes = _solid_color_jpeg_bytes((40, 80, 180))
        rgb = photo_palette._dominant_accent_color(image_bytes)
        self.assertIsNotNone(rgb)
        r, g, b = rgb
        self.assertLess(r, g)
        self.assertLess(g, b)

    def test_falls_back_to_most_common_color_when_nothing_passes_thresholds(self):
        # Pure white fails every saturation/value threshold in this module --
        # must still return something (the most common color) rather than None.
        image_bytes = _solid_color_jpeg_bytes((255, 255, 255))
        rgb = photo_palette._dominant_accent_color(image_bytes)
        self.assertEqual(rgb, (255, 255, 255))

    def test_undecodable_bytes_return_none_instead_of_raising(self):
        self.assertIsNone(photo_palette._dominant_accent_color(b"not an image at all"))


class BuildPaletteTests(unittest.TestCase):
    def test_builds_accent_dark_and_soft_variants(self):
        result = photo_palette._build_palette((104, 125, 157))
        self.assertEqual(result["accent"], "#687d9d")
        self.assertEqual(result["accent_dark"], "#394456")
        self.assertEqual(result["accent_soft"], "#687d9d33")


class RgbToHexTests(unittest.TestCase):
    def test_basic_conversion(self):
        self.assertEqual(photo_palette._rgb_to_hex(104, 125, 157), "#687d9d")

    def test_clamps_out_of_range_values(self):
        self.assertEqual(photo_palette._rgb_to_hex(-10, 128, 300), "#0080ff")


class GetPaletteIntegrationTests(unittest.TestCase):
    """End-to-end through get_palette() itself, with a single MockTransport
    client standing in for both the Details and Media calls."""

    def test_full_success_path(self):
        image_bytes = _solid_color_jpeg_bytes((40, 80, 180))

        def handler(request):
            if "media" in str(request.url):
                return httpx.Response(200, content=image_bytes)
            return httpx.Response(200, json={"photos": [{"name": PHOTO_NAME}]})

        with _make_client(handler) as client:
            result = photo_palette.get_palette("place-1", "key", client)
        self.assertIsNotNone(result)
        self.assertIn("accent", result)
        self.assertIn("accent_dark", result)
        self.assertIn("accent_soft", result)

    def test_no_photos_returns_none(self):
        def handler(request):
            return httpx.Response(200, json={"photos": []})

        with _make_client(handler) as client:
            self.assertIsNone(photo_palette.get_palette("place-1", "key", client))

    def test_photo_fetch_failure_returns_none(self):
        def handler(request):
            if "media" in str(request.url):
                return httpx.Response(500, text="server error")
            return httpx.Response(200, json={"photos": [{"name": PHOTO_NAME}]})

        with _make_client(handler) as client:
            self.assertIsNone(photo_palette.get_palette("place-1", "key", client))

    def test_undecodable_photo_bytes_returns_none(self):
        def handler(request):
            if "media" in str(request.url):
                return httpx.Response(200, content=b"not an image")
            return httpx.Response(200, json={"photos": [{"name": PHOTO_NAME}]})

        with _make_client(handler) as client:
            self.assertIsNone(photo_palette.get_palette("place-1", "key", client))


if __name__ == "__main__":
    unittest.main()
