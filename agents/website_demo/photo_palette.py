"""Derives a color palette from a lead's real Google Places photo, without
ever storing or redistributing the photo itself.

Google's Places API terms require photos be fetched live and forbid
caching the photo content (see
https://developers.google.com/maps/documentation/places/web-service/policies).
So this module fetches one photo per lead, computes a small set of hex
colors from it in memory, and discards the image bytes immediately --
only the derived numbers are ever written anywhere.
"""

import colorsys

import httpx
from PIL import Image
import io

DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
MEDIA_URL = "https://places.googleapis.com/v1/{photo_name}/media"

MIN_SATURATION = 0.25
MIN_VALUE = 0.15
MAX_VALUE = 0.92


def get_palette(place_id: str, api_key: str, client: httpx.Client | None = None) -> dict | None:
    """Returns {"accent": "#rrggbb", "accent_dark": "#rrggbb", "accent_soft": "#rrggbbaa"}
    or None if no usable photo/color was found (caller should fall back to
    the template's default palette)."""
    owns_client = client is None
    client = client or httpx.Client(timeout=10.0)
    try:
        photo_name = _get_first_photo_name(place_id, api_key, client)
        if not photo_name:
            return None

        image_bytes = _fetch_photo_bytes(photo_name, api_key, client)
        if not image_bytes:
            return None

        accent_rgb = _dominant_accent_color(image_bytes)
        if not accent_rgb:
            return None

        return _build_palette(accent_rgb)
    finally:
        if owns_client:
            client.close()


def _get_first_photo_name(place_id: str, api_key: str, client: httpx.Client) -> str | None:
    url = DETAILS_URL.format(place_id=place_id)
    headers = {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": "photos"}
    try:
        response = client.get(url, headers=headers, timeout=10.0)
        response.raise_for_status()
        photos = response.json().get("photos", [])
    except (httpx.HTTPError, ValueError):
        # ValueError covers response.json() on a non-JSON body -- same
        # "never crash the batch, just skip this lead's palette" contract
        # as every other failure mode in this module.
        return None
    return photos[0]["name"] if photos else None


def _fetch_photo_bytes(photo_name: str, api_key: str, client: httpx.Client) -> bytes | None:
    url = MEDIA_URL.format(photo_name=photo_name)
    params = {"maxWidthPx": 200, "key": api_key}
    try:
        response = client.get(url, params=params, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    return response.content


def _dominant_accent_color(image_bytes: bytes) -> tuple[int, int, int] | None:
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img = img.convert("RGB")
            img.thumbnail((100, 100))
            colors = img.getcolors(maxcolors=10_000) or []
    except OSError:
        # Not a decodable image -- same degrade-gracefully contract as
        # every other failure mode in this module.
        return None

    colors.sort(key=lambda c: c[0], reverse=True)

    for _count, (r, g, b) in colors:
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s >= MIN_SATURATION and MIN_VALUE <= v <= MAX_VALUE:
            return (r, g, b)

    return colors[0][1] if colors else None


def _build_palette(rgb: tuple[int, int, int]) -> dict:
    r, g, b = rgb
    accent = _rgb_to_hex(r, g, b)
    accent_dark = _rgb_to_hex(int(r * 0.55), int(g * 0.55), int(b * 0.55))
    return {
        "accent": accent,
        "accent_dark": accent_dark,
        "accent_soft": f"{accent}33",
    }


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    r, g, b = (max(0, min(255, v)) for v in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"
