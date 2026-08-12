"""Shared HTTP retry-with-backoff helper for Discovery's API clients
(places_client.py, psi_client.py). Two independent copies of this same
retry loop existed before -- one duplicated across two functions in
places_client.py, one in psi_client.py -- and had already drifted apart:
only the psi_client.py copy caught transport-level failures and unsafe
JSON parsing. This is the one implementation both use now.
"""

import time
from collections.abc import Callable

import httpx

RETRYABLE_STATUSES = (429, 500, 502, 503)


def request_with_retry(
    request_fn: Callable[[], httpx.Response],
    error_cls: type[Exception],
    context: str,
    max_retries: int = 3,
) -> httpx.Response:
    """Calls request_fn() -- a zero-argument callable performing exactly
    one HTTP request, e.g. `lambda: client.get(url, ...)` -- up to
    max_retries times.

    - A 200 response is returned immediately.
    - A retryable status (429/500/502/503) retries with exponential
      backoff (2**attempt seconds between attempts).
    - Any other non-200 status raises error_cls immediately, no retry.
    - An httpx.HTTPError from request_fn() itself (DNS failure, timeout,
      connection refused) raises error_cls immediately -- a transport
      failure isn't the kind of thing a fixed backoff schedule reliably
      resolves, so it's treated like a non-retryable status rather than
      retried blind.
    - Exhausting all retries on a retryable status raises error_cls with
      the last attempt's status/body.

    `context` is a short label (e.g. "Places API", "PSI API") used only
    to make the raised error messages identify which service failed.
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            response = request_fn()
        except httpx.HTTPError as exc:
            raise error_cls(f"{context} request failed: {exc}") from exc
        if response.status_code == 200:
            return response
        if response.status_code in RETRYABLE_STATUSES:
            last_error = f"{response.status_code}: {response.text}"
            time.sleep(2 ** attempt)
            continue
        raise error_cls(f"{context} error {response.status_code}: {response.text}")
    raise error_cls(f"{context} failed after {max_retries} retries: {last_error}")


def parse_json_response(response: httpx.Response, error_cls: type[Exception], context: str) -> dict:
    """Safely parses a successful response's JSON body, raising error_cls
    instead of a raw ValueError/JSONDecodeError on a malformed body (seen
    in practice: a 200 status with an HTML error page instead of real
    JSON, from Google's own infrastructure)."""
    try:
        return response.json()
    except ValueError as exc:
        raise error_cls(f"{context} returned invalid JSON: {exc}") from exc
