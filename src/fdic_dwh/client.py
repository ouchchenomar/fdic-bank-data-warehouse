"""HTTP client for the FDIC BankFind Suite API: stable pagination and retries."""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import requests

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class FdicApiError(RuntimeError):
    """The API refused the request or kept failing after every retry."""


class SourceChangedError(FdicApiError):
    """The FDIC index was rebuilt while we were paginating: pages may be inconsistent."""


@dataclass(frozen=True)
class Page:
    url: str
    offset: int
    rows: list[dict[str, Any]]
    total: int
    index_name: str | None
    index_created_at: str | None


class FdicClient:
    def __init__(
        self,
        base_url: str,
        *,
        page_size: int = 1000,
        timeout: float = 60,
        max_retries: int = 5,
        backoff_base: float = 1.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "fdic-dwh/1.0")
        self.sleep = sleep

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after and retry_after.isdigit():
            return float(retry_after)
        return self.backoff_base * 2**attempt + random.uniform(0, self.backoff_base)

    def get(self, endpoint: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """GET with exponential backoff on 429, 5xx and network errors."""
        url = f"{self.base_url}{endpoint}"
        for attempt in range(self.max_retries + 1):
            retry_after = None
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code == 200:
                    return response.url, response.json()
                if response.status_code not in RETRYABLE_STATUS:
                    raise FdicApiError(
                        f"HTTP {response.status_code} on {response.url}: {response.text[:200]}"
                    )
                error = f"HTTP {response.status_code}"
                retry_after = response.headers.get("Retry-After")
            if attempt == self.max_retries:
                raise FdicApiError(f"gave up after {attempt + 1} attempts on {url}: {error}")
            self.sleep(self._delay(attempt, retry_after))
        raise AssertionError("unreachable")

    def iter_pages(
        self,
        endpoint: str,
        *,
        fields: list[str],
        sort_by: str,
        filters: str | None = None,
        sort_order: str = "ASC",
        page_size: int | None = None,
    ) -> Iterator[Page]:
        """Yield pages sorted on a stable key until the announced total is reached."""
        offset = 0
        first_index: str | None = None
        while True:
            params: dict[str, Any] = {
                "fields": ",".join(fields),
                "sort_by": sort_by,
                "sort_order": sort_order,
                "limit": page_size or self.page_size,
                "offset": offset,
            }
            if filters:
                params["filters"] = filters
            url, body = self.get(endpoint, params)
            meta = body.get("meta") or {}
            index = meta.get("index") or {}
            if offset == 0:
                first_index = index.get("name")
            elif index.get("name") != first_index:
                raise SourceChangedError(
                    f"source index changed during pagination: {first_index} -> {index.get('name')}"
                )
            rows = [item["data"] for item in body.get("data") or []]
            total = int(meta.get("total") or 0)
            yield Page(url, offset, rows, total, index.get("name"), index.get("createTimestamp"))
            offset += len(rows)
            if not rows or offset >= total:
                return
