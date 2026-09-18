"""Facebook Playwright module tests (Unit 4 slice).

STRICT TDD: written BEFORE src/adapters/facebook.py.
Covers design #28 + spec #27 (facebook-playwright capability):

- FixtureLoader returns recorded listings (CI never touches live FB)
- FB_FIXTURE=1 forces fixture fallback
- Missing auth_state.json falls back to fixture (no login wall in CI)
- Gentle limits: limit<=0 -> [], limit>60 clamped to MAX_LIMIT
- DOM card parser maps raw card dicts to shared Listing schema
- Embedded-JSON parser maps page payloads to Listings
- Checkpoint/login-wall detection aborts the live run
- Transient-error backoff retries then succeeds
- Fixture path works WITHOUT playwright installed (no live network)
- FacebookAdapter satisfies the MarketplaceAdapter protocol

No live network, no credentials, no browser launch in any test.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "fb_listings.json"


def _card(
    item_id: str = "FB1",
    title: str = "Bici rodado 29",
    price: str | None = "$ 85.000",
    location: str | None = "Palermo",
) -> dict:
    return {
        "id": item_id,
        "title": title,
        "price_text": price,
        "url": f"https://www.facebook.com/marketplace/item/{item_id}",
        "image_url": f"https://example.com/img/{item_id}.jpg",
        "seller": "Vendedor Demo",
        "location": location,
    }


def test_adapter_satisfies_protocol():
    from src.adapters.base import MarketplaceAdapter
    from src.adapters.facebook import FacebookAdapter

    adapter = FacebookAdapter(use_fixture=True)
    assert isinstance(adapter, MarketplaceAdapter)
    adapter.close()


def test_fixture_loader_returns_recorded_listings():
    from src.adapters.facebook import FixtureLoader

    loader = FixtureLoader(str(FIXTURE_PATH))
    listings = list(loader.load())
    assert len(listings) == 3
    assert listings[0].id == "FB101"
    assert listings[0].price == Decimal(85000)
    assert listings[2].price is None  # no-price card stays valid


def test_fixture_env_var_forces_fixture(monkeypatch):
    from src.adapters.facebook import FacebookAdapter

    monkeypatch.setenv("FB_FIXTURE", "1")
    adapter = FacebookAdapter(auth_state="/nonexistent/auth_state.json")
    results = list(adapter.search("bici", 10))
    assert len(results) == 3
    assert all(r.id.startswith("FB") for r in results)
    adapter.close()


def test_search_falls_back_to_fixture_without_auth_state(tmp_path, monkeypatch):
    from src.adapters.facebook import FacebookAdapter

    monkeypatch.delenv("FB_FIXTURE", raising=False)
    missing = str(tmp_path / "no-auth_state.json")
    assert not os.path.exists(missing)
    adapter = FacebookAdapter(auth_state=missing, use_fixture=False)
    results = list(adapter.search("bici", 10))
    # No login wall in CI: missing storage_state -> recorded fixture.
    assert len(results) == 3
    adapter.close()


def test_search_gentle_limits_clamp(monkeypatch):
    from src.adapters.facebook import MAX_LIMIT, FacebookAdapter

    monkeypatch.setenv("FB_FIXTURE", "1")
    adapter = FacebookAdapter()
    assert list(adapter.search("bici", 0)) == []
    assert list(adapter.search("bici", -5)) == []
    capped = list(adapter.search("bici", 10_000))
    assert len(capped) <= MAX_LIMIT
    adapter.close()


def test_search_truncates_fixture_to_limit(monkeypatch):
    from src.adapters.facebook import FacebookAdapter

    monkeypatch.setenv("FB_FIXTURE", "1")
    adapter = FacebookAdapter()
    results = list(adapter.search("bici", 2))
    assert [r.id for r in results] == ["FB101", "FB102"]
    adapter.close()


def test_parse_card_maps_dom_to_listing():
    from src.adapters.facebook import parse_card

    listing = parse_card(_card())
    assert listing.id == "FB1"
    assert listing.title == "Bici rodado 29"
    assert listing.price == Decimal(85000)
    assert listing.currency == "ARS"
    assert listing.url.startswith("https://www.facebook.com/marketplace/item/")
    assert listing.location == "Palermo"


def test_parse_card_handles_missing_price():
    from src.adapters.facebook import parse_card

    listing = parse_card(_card(price=None, location=None))
    assert listing.price is None
    assert listing.location is None


def test_parse_embedded_json_maps_to_listings():
    from src.adapters.facebook import parse_embedded_json

    payload = {
        "marketplace_search": {
            "results": [
                {
                    "id": "FB201",
                    "marketplace_listing_title": "Bici fixture JSON",
                    "listing_price": {"amount": "95000", "currency": "ARS"},
                    "primary_listing_photo": {
                        "image": {"uri": "https://example.com/p.jpg"}
                    },
                    "location": {"reverse_geocode": {"city": "Belgrano"}},
                }
            ]
        }
    }
    listings = parse_embedded_json(payload)
    assert len(listings) == 1
    assert listings[0].id == "FB201"
    assert listings[0].price == Decimal(95000)
    assert listings[0].location == "Belgrano"


def test_checkpoint_detection_aborts_live_run():
    from src.adapters.facebook import (
        FacebookCheckpointError,
        is_checkpoint,
        raise_if_checkpoint,
    )

    assert is_checkpoint("Log in to continue to Marketplace")
    assert is_checkpoint("checkpoint: verify your account")
    assert not is_checkpoint("Bicicleta rodado 29 en Palermo")
    with pytest.raises(FacebookCheckpointError):
        raise_if_checkpoint("Please log in or checkpoint to continue")


def test_backoff_retries_transient_errors_then_succeeds(monkeypatch):
    from src.adapters.facebook import run_with_backoff

    monkeypatch.setattr("time.sleep", lambda _: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("transient")
        return "ok"

    assert run_with_backoff(flaky, max_retries=3, base=0) == "ok"
    assert calls["n"] == 3


def test_backoff_raises_after_retries_exhausted(monkeypatch):
    from src.adapters.facebook import run_with_backoff

    monkeypatch.setattr("time.sleep", lambda _: None)

    def always_fail():
        raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        run_with_backoff(always_fail, max_retries=2, base=0)


def test_fixture_path_needs_no_playwright(monkeypatch):
    """Fixture fallback must work even when playwright is not installed."""
    import sys

    from src.adapters.facebook import FacebookAdapter

    monkeypatch.setenv("FB_FIXTURE", "1")
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    adapter = FacebookAdapter()
    results = list(adapter.search("bici", 2))
    assert len(results) == 2
    adapter.close()


def test_get_item_from_fixture(monkeypatch):
    from src.adapters.facebook import FacebookAdapter

    monkeypatch.setenv("FB_FIXTURE", "1")
    adapter = FacebookAdapter()
    found = adapter.get_item("FB101")
    assert found is not None
    assert found.title.startswith("Bicicleta rodado 29")
    assert adapter.get_item("FB-missing") is None
    adapter.close()


def test_fixture_file_is_valid_json_with_expected_shape():
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw["listings"], list)
    assert len(raw["listings"]) == 3
    for entry in raw["listings"]:
        assert {"id", "title", "url"} <= set(entry)
