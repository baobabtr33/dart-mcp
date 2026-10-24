"""Async HTTP client for the OpenDART API (https://opendart.fss.or.kr).

Handles authentication, DART status codes, retries with backoff, and a small
in-memory TTL cache so repeated agent calls don't burn the 20,000/day quota.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://opendart.fss.or.kr/api"

# DART returns HTTP 200 with a `status` field; these are the documented codes.
STATUS_MESSAGES: dict[str, str] = {
    "000": "OK",
    "010": "Unregistered API key",
    "011": "API key is not usable (suspended)",
    "012": "Access from this IP is not allowed",
    "013": "No data found for the query",
    "014": "File does not exist",
    "020": "Daily request limit exceeded (20,000/day)",
    "021": "Too many companies requested (max 100)",
    "100": "Invalid field value",
    "101": "Unauthorized access",
    "800": "DART system maintenance",
    "900": "Undefined DART error",
    "901": "API key expired (personal info retention period passed)",
}

NO_DATA = "013"
_RETRYABLE_STATUS = {"800", "900"}


class DartError(Exception):
    """Raised when DART returns a non-success status."""

    def __init__(self, status: str, message: str | None = None):
        self.status = status
        detail = STATUS_MESSAGES.get(status, "Unknown status")
        super().__init__(f"DART error {status}: {detail}" + (f" ({message})" if message else ""))


class DartClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
        cache_ttl: float = 600.0,
        max_concurrency: int = 5,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_key = api_key or os.environ.get("DART_API_KEY", "")
        if not self.api_key:
            raise RuntimeError(
                "DART_API_KEY is not set. Get a free key at https://opendart.fss.or.kr "
                "and pass it via the DART_API_KEY environment variable."
            )
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": "dart-mcp/0.1"},
        )
        self._max_retries = max_retries
        self._cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, Any]] = {}
        self._sem = asyncio.Semaphore(max_concurrency)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, endpoint: str, params: dict[str, Any]) -> httpx.Response:
        query = {k: v for k, v in params.items() if v not in (None, "")}
        query["crtfc_key"] = self.api_key
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                async with self._sem:
                    resp = await self._http.get(f"/{endpoint}", params=query)
                if resp.status_code >= 500 or resp.status_code == 429:
                    raise httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=resp.request, response=resp)
                resp.raise_for_status()
                return resp
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status is not None and status < 500 and status != 429:
                    raise
                delay = 2**attempt
                log.warning("DART %s failed (%s); retry in %ss", endpoint, exc, delay)
                await asyncio.sleep(delay)
        raise RuntimeError(f"DART request to {endpoint} failed after retries: {last_exc}")

    def _cache_get(self, key: str) -> Any | None:
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self._cache_ttl:
            return hit[1]
        self._cache.pop(key, None)
        return None

    def _cache_put(self, key: str, value: Any) -> None:
        if len(self._cache) > 512:
            # Drop oldest quarter; cheap and good enough for a single-user server.
            for k in sorted(self._cache, key=lambda k: self._cache[k][0])[:128]:
                del self._cache[k]
        self._cache[key] = (time.monotonic(), value)

    async def get_json(self, endpoint: str, **params: Any) -> dict[str, Any]:
        """Call a `.json` endpoint. Returns the payload; `list` is [] when DART has no data."""
        key = endpoint + json.dumps(params, sort_keys=True, default=str)
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        for attempt in range(self._max_retries):
            data = (await self._request(endpoint, params)).json()
            status = data.get("status", "000")
            if status in _RETRYABLE_STATUS and attempt < self._max_retries - 1:
                await asyncio.sleep(2**attempt)
                continue
            break

        if status == NO_DATA:
            data = {"status": NO_DATA, "message": data.get("message"), "list": []}
        elif status != "000":
            raise DartError(status, data.get("message"))

        self._cache_put(key, data)
        return data

    async def get_zip(self, endpoint: str, **params: Any) -> bytes:
        """Call an endpoint that returns a ZIP archive (corpCode.xml, document.xml)."""
        resp = await self._request(endpoint, params)
        content = resp.content
        if content[:2] == b"PK":
            return content
        # Errors come back as XML or JSON instead of a ZIP.
        text = content.decode("utf-8", errors="replace")
        status = _extract_status(text)
        raise DartError(status or "900", None if status else text[:200])


def _extract_status(text: str) -> str | None:
    try:
        return json.loads(text).get("status")
    except (ValueError, AttributeError):
        pass
    start = text.find("<status>")
    end = text.find("</status>")
    if start != -1 and end != -1:
        return text[start + len("<status>") : end].strip()
    return None
