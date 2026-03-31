from __future__ import annotations

import time

import httpx


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

ALTERNATE_HEADERS = {
    **DEFAULT_HEADERS,
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Safari/605.1.15"
    ),
    "Accept": "*/*",
}


def fetch_text(url: str, *, timeout: float, referer: str = "") -> str:
    headers_candidates = [DEFAULT_HEADERS, ALTERNATE_HEADERS]
    last_error: Exception | None = None

    for headers in headers_candidates:
        request_headers = dict(headers)
        if referer:
            request_headers["Referer"] = referer

        for attempt in range(3):
            try:
                with httpx.Client(
                    timeout=timeout,
                    follow_redirects=True,
                    headers=request_headers,
                ) as client:
                    response = client.get(url)
                    response.raise_for_status()
                    return response.text
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code not in {403, 429, 500, 502, 503, 504}:
                    raise
            except httpx.HTTPError as exc:
                last_error = exc

            time.sleep(min(2 * (attempt + 1), 5))

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")
