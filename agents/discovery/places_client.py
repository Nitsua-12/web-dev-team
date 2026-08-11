"""Thin wrapper around the Google Places API (New) Text Search endpoint.

Text Search (New) returns website/phone/address directly in the search
response when requested via the field mask, so no separate Place Details
call is needed for this use case.

Field selection controls Google's billing tier (Pro vs Enterprise) -- the
fields requested below (websiteUri, nationalPhoneNumber) are contact
fields and will bill at the higher tier. Confirm current pricing at
https://developers.google.com/maps/documentation/places/web-service/usage-and-billing
before running a large batch.
"""

import time

import httpx

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.websiteUri",
    "places.nationalPhoneNumber",
    "places.addressComponents",
    "nextPageToken",
])

MAX_PAGES = 3  # Text Search (New) caps at 60 results (3 pages of 20)


class PlacesApiError(RuntimeError):
    pass


def search_text(query: str, api_key: str, max_pages: int = MAX_PAGES) -> list[dict]:
    """Run a text search query and return all places across up to max_pages pages."""
    if not api_key:
        raise PlacesApiError("GOOGLE_PLACES_API_KEY is not set")

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }

    all_places: list[dict] = []
    page_token = None

    with httpx.Client(timeout=15.0) as client:
        for _ in range(max_pages):
            body = {"textQuery": query}
            if page_token:
                body["pageToken"] = page_token
                # Google requires a short delay before a pageToken becomes valid
                time.sleep(2)

            response = _post_with_retry(client, headers, body)
            data = response.json()
            all_places.extend(data.get("places", []))

            page_token = data.get("nextPageToken")
            if not page_token:
                break

    return all_places


def get_place_details(place_id: str, api_key: str, field_mask: str = "websiteUri", max_retries: int = 3) -> dict:
    """Look up a single already-known place by ID -- used by the reverify
    agent to recheck a lead's current website status without a fresh
    text search. Distinct from search_text: this is a GET against one
    resource, not a POST search."""
    if not api_key:
        raise PlacesApiError("GOOGLE_PLACES_API_KEY is not set")

    url = DETAILS_URL.format(place_id=place_id)
    headers = {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": field_mask}

    last_error = None
    with httpx.Client(timeout=15.0) as client:
        for attempt in range(max_retries):
            response = client.get(url, headers=headers)
            if response.status_code == 200:
                return response.json()
            if response.status_code in (429, 500, 502, 503):
                last_error = f"{response.status_code}: {response.text}"
                time.sleep(2 ** attempt)
                continue
            raise PlacesApiError(f"Places API error {response.status_code}: {response.text}")
    raise PlacesApiError(f"Places API failed after {max_retries} retries: {last_error}")


def _post_with_retry(client: httpx.Client, headers: dict, body: dict, max_retries: int = 3) -> httpx.Response:
    last_error = None
    for attempt in range(max_retries):
        response = client.post(SEARCH_URL, headers=headers, json=body)
        if response.status_code == 200:
            return response
        if response.status_code in (429, 500, 502, 503):
            last_error = f"{response.status_code}: {response.text}"
            time.sleep(2 ** attempt)
            continue
        raise PlacesApiError(f"Places API error {response.status_code}: {response.text}")
    raise PlacesApiError(f"Places API failed after {max_retries} retries: {last_error}")


def extract_address_component(place: dict, component_type: str) -> str | None:
    for component in place.get("addressComponents", []):
        if component_type in component.get("types", []):
            return component.get("shortText") or component.get("longText")
    return None
