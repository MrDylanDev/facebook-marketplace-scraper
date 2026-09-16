"""MercadoLibre public REST API adapter (Unit 2 slice).

Implements the ``MarketplaceAdapter`` contract from design #28 against the
public MercadoLibre API — no auth required:

- ``GET /sites/{site_id}/search`` with ``q`` / ``limit`` / ``offset`` paging
- ``GET /items/{item_id}`` for single-item detail
- HTTP 429 retries with exponential backoff + jitter
"""

from __future__ import annotations

import random
import time
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

import httpx

from src.models.listing import Listing

BASE_URL = "https://api.mercadolibre.com"
DEFAULT_SITE_ID = "MLA"
DEFAULT_PAGE_SIZE = 50
DEFAULT_MAX_RETRIES = 4
DEFAULT_BACKOFF_BASE = 0.5
DEFAULT_TIMEOUT = 15.0


class MercadoLibreAdapter:
    """Search MercadoLibre via its public REST API.

    An ``httpx.Client`` may be injected (tests use ``MockTransport``);
    otherwise a default client is created and owned by this adapter.
    """

    def __init__(
        self,
        site_id: str = DEFAULT_SITE_ID,
        client: httpx.Client | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        page_size: int = DEFAULT_PAGE_SIZE,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.site_id = site_id
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.page_size = page_size
        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            self._client = httpx.Client(
                base_url=BASE_URL,
                timeout=timeout,
                headers={"User-Agent": "marketplace-scraper/0.1 (portfolio demo)"},
            )
            self._owns_client = True

    def search(self, query: str, limit: int) -> Iterable[Listing]:
        """Yield up to ``limit`` listings, paging with ``limit``/``offset``."""
        if limit <= 0:
            return []
        collected: list[Listing] = []
        offset = 0
        while len(collected) < limit:
            page_size = min(self.page_size, limit - len(collected))
            payload = self._get_with_retry(
                f"{BASE_URL}/sites/{self.site_id}/search",
                params={"q": query, "limit": page_size, "offset": offset},
            )
            items = payload.get("results", [])
            if not items:
                break
            for raw in items[: limit - len(collected)]:
                collected.append(_listing_from_search_item(raw))
            offset += len(items)
            # Stop paging when the server reports no more results.
            # Prefer paging.total (always present in the real API); fall
            # back to the short-page heuristic only when total is absent.
            # An empty page or the reached limit stops paging regardless:
            # servers may return short non-final pages, so a short page
            # alone must not terminate pagination when total says more.
            total = payload.get("paging", {}).get("total")
            if total is not None:
                if offset >= total:
                    break
            elif len(items) < page_size:
                break
        return collected

    def get_item(self, item_id: str) -> Listing | None:
        """Fetch one item by id; ``None`` when the API returns 404."""
        try:
            payload = self._get_with_retry(f"{BASE_URL}/items/{item_id}", params={})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return _listing_from_detail(payload)

    def close(self) -> None:
        """Close the owned HTTP client (no-op for injected clients)."""
        if self._owns_client:
            self._client.close()

    def _get_with_retry(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET ``url`` with exponential backoff + jitter on HTTP 429."""
        last_error: httpx.HTTPStatusError | None = None
        for attempt in range(self.max_retries + 1):
            response = self._client.get(url, params=params)
            if response.status_code == 429:
                last_error = httpx.HTTPStatusError(
                    "rate limited (429)",
                    request=response.request,
                    response=response,
                )
                if attempt < self.max_retries:
                    delay = self.backoff_base * (2**attempt) + random.uniform(
                        0, self.backoff_base
                    )
                    if delay > 0:
                        time.sleep(delay)
                    continue
                raise last_error
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {}
        raise last_error or httpx.HTTPStatusError(
            "rate limited (429)",
            request=None,
            response=None,  # type: ignore[arg-type]
        )


def _listing_from_search_item(raw: dict[str, Any]) -> Listing:
    price = raw.get("price")
    seller = raw.get("seller") or {}
    address = raw.get("address") or {}
    location = " / ".join(
        part for part in (address.get("city_name"), address.get("state_name")) if part
    )
    return Listing(
        id=str(raw.get("id", "")),
        title=str(raw.get("title", "")),
        price=Decimal(str(price)) if price is not None else None,
        currency=raw.get("currency_id"),
        url=str(raw.get("permalink", "")),
        image_url=raw.get("thumbnail"),
        seller=seller.get("nickname") or None,
        location=location or None,
    )


def _listing_from_detail(raw: dict[str, Any]) -> Listing:
    price = raw.get("price")
    pictures = raw.get("pictures") or []
    image_url = pictures[0].get("url") if pictures else None
    seller_id = raw.get("seller_id")
    return Listing(
        id=str(raw.get("id", "")),
        title=str(raw.get("title", "")),
        price=Decimal(str(price)) if price is not None else None,
        currency=raw.get("currency_id"),
        url=str(raw.get("permalink", "")),
        image_url=image_url,
        seller=str(seller_id) if seller_id is not None else None,
        location=None,
    )
