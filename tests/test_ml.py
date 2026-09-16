"""MercadoLibre adapter tests (Unit 2 slice).

STRICT TDD: written BEFORE src/adapters/mercado_libre.py.
Covers design #28 + spec #27 (mercado-libre-api capability):
- search pagination via limit/offset
- 429 exponential backoff with retry
- item detail mapping to shared Listing schema
- adapter satisfies MarketplaceAdapter protocol

All HTTP is mocked with httpx.MockTransport. No live network, no Facebook.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest


def _search_item(
    item_id: str = "MLA123",
    title: str = "Bicicleta rodado 29",
    price: float | None = 150000.0,
    currency_id: str = "ARS",
) -> dict:
    return {
        "id": item_id,
        "title": title,
        "price": price,
        "currency_id": currency_id,
        "permalink": f"https://articulo.mercadolibre.com.ar/{item_id}",
        "thumbnail": f"https://http2.mlstatic.com/{item_id}.jpg",
        "seller": {"nickname": "seller1"},
        "address": {"city_name": "Buenos Aires", "state_name": "Capital Federal"},
    }


def _search_payload(items: list[dict], total: int | None = None) -> dict:
    return {
        "results": items,
        "paging": {"total": total if total is not None else len(items)},
    }


def _make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_adapter_satisfies_protocol():
    from src.adapters.base import MarketplaceAdapter
    from src.adapters.mercado_libre import MercadoLibreAdapter

    adapter = MercadoLibreAdapter(
        client=_make_client(
            lambda request: httpx.Response(200, json=_search_payload([]))
        )
    )
    assert isinstance(adapter, MarketplaceAdapter)
    adapter.close()


def test_search_single_page_maps_to_listings():
    from src.adapters.mercado_libre import MercadoLibreAdapter

    payload = _search_payload([_search_item(), _search_item(item_id="MLA456")])

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/sites/MLA/search" in request.url.path
        return httpx.Response(200, json=payload)

    adapter = MercadoLibreAdapter(client=_make_client(handler), backoff_base=0)
    results = list(adapter.search("bici", 10))

    assert len(results) == 2
    first = results[0]
    assert first.id == "MLA123"
    assert first.title == "Bicicleta rodado 29"
    assert first.price == Decimal(150000)
    assert first.currency == "ARS"
    assert first.url.startswith("https://")
    assert first.image_url is not None
    assert first.seller == "seller1"
    assert first.location is not None
    adapter.close()


def test_search_paginates_with_offset_until_limit():
    from src.adapters.mercado_libre import MercadoLibreAdapter

    seen_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        offset = int(params.get("offset", 0))
        seen_offsets.append(offset)
        if offset == 0:
            items = [_search_item(item_id="MLA1"), _search_item(item_id="MLA2")]
        elif offset == 2:
            items = [_search_item(item_id="MLA3")]
        else:
            items = []
        return httpx.Response(200, json=_search_payload(items, total=3))

    adapter = MercadoLibreAdapter(client=_make_client(handler), backoff_base=0)
    results = list(adapter.search("bici", 3))

    assert [item.id for item in results] == ["MLA1", "MLA2", "MLA3"]
    assert seen_offsets[0] == 0
    assert 2 in seen_offsets  # second page fetched with offset
    adapter.close()


def test_search_respects_limit_without_extra_requests():
    from src.adapters.mercado_libre import MercadoLibreAdapter

    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        items = [_search_item(item_id=f"MLA{i}") for i in range(5)]
        return httpx.Response(200, json=_search_payload(items, total=5))

    adapter = MercadoLibreAdapter(client=_make_client(handler), backoff_base=0)
    results = list(adapter.search("bici", 2))

    assert len(results) == 2
    assert calls["count"] == 1  # no second page when limit already satisfied
    adapter.close()


def test_search_retries_429_with_backoff_then_succeeds():
    from src.adapters.mercado_libre import MercadoLibreAdapter

    calls = {"count": 0}
    payload = _search_payload([_search_item()])

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, json={"message": "too many requests"})
        return httpx.Response(200, json=payload)

    adapter = MercadoLibreAdapter(client=_make_client(handler), backoff_base=0)
    results = list(adapter.search("bici", 5))

    assert len(results) == 1
    assert calls["count"] == 2  # retried once after 429
    adapter.close()


def test_search_raises_after_429_retries_exhausted():
    from src.adapters.mercado_libre import MercadoLibreAdapter

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "too many requests"})

    adapter = MercadoLibreAdapter(
        client=_make_client(handler), backoff_base=0, max_retries=2
    )
    with pytest.raises(httpx.HTTPStatusError):
        list(adapter.search("bici", 5))
    adapter.close()


def test_get_item_returns_listing_from_detail():
    from src.adapters.mercado_libre import MercadoLibreAdapter

    detail = {
        "id": "MLA123",
        "title": "Bicicleta rodado 29",
        "price": 150000,
        "currency_id": "ARS",
        "permalink": "https://articulo.mercadolibre.com.ar/MLA123",
        "pictures": [{"url": "https://http2.mlstatic.com/pic.jpg"}],
        "seller_id": 42,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/items/MLA123"
        return httpx.Response(200, json=detail)

    adapter = MercadoLibreAdapter(client=_make_client(handler), backoff_base=0)
    listing = adapter.get_item("MLA123")

    assert listing is not None
    assert listing.id == "MLA123"
    assert listing.price == Decimal(150000)
    assert listing.image_url == "https://http2.mlstatic.com/pic.jpg"
    adapter.close()


def test_get_item_returns_none_on_404():
    from src.adapters.mercado_libre import MercadoLibreAdapter

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "not found"})

    adapter = MercadoLibreAdapter(client=_make_client(handler), backoff_base=0)
    assert adapter.get_item("MLA-missing") is None
    adapter.close()


def test_search_empty_results_returns_empty():
    from src.adapters.mercado_libre import MercadoLibreAdapter

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_search_payload([], total=0))

    adapter = MercadoLibreAdapter(client=_make_client(handler), backoff_base=0)
    assert list(adapter.search("zzz-no-match", 10)) == []
    adapter.close()
