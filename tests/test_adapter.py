"""Contract tests for MarketplaceAdapter (Unit 1 scaffold slice).

STRICT TDD: written BEFORE src/adapters/base.py and src/models/listing.py.
Verifies the adapter contract from design #28 and spec #27:
- Listing schema shared by all adapters
- MarketplaceAdapter.search/detail contract
- Adapter interchangeability (ML <-> FB share schema)
"""

from collections.abc import Iterable
from decimal import Decimal

import pytest
from pydantic import ValidationError


def test_listing_requires_id_title_url():
    from src.models.listing import Listing

    with pytest.raises(ValidationError):
        Listing(title="Bike", url="https://example.com/1")  # type: ignore[call-arg]


def test_listing_valid_minimal():
    from src.models.listing import Listing

    listing = Listing(id="1", title="Bike", url="https://example.com/1")
    assert listing.id == "1"
    assert listing.title == "Bike"
    assert listing.price is None


def test_listing_valid_full():
    from src.models.listing import Listing

    listing = Listing(
        id="abc123",
        title="Bicicleta rodado 29",
        price=Decimal("150000.00"),
        currency="ARS",
        url="https://example.com/item/abc123",
        image_url="https://example.com/img/abc123.jpg",
        seller="seller1",
        location="Buenos Aires",
    )
    assert listing.currency == "ARS"
    assert listing.seller == "seller1"


def test_adapter_protocol_contract():
    from src.adapters.base import MarketplaceAdapter
    from src.models.listing import Listing

    class FakeAdapter:
        def search(self, query: str, limit: int) -> Iterable[Listing]:
            return [
                Listing(id="1", title=f"{query} item", url="https://example.com/1")
            ][:limit]

        def get_item(self, item_id: str) -> Listing | None:
            if item_id == "1":
                return Listing(id="1", title="item", url="https://example.com/1")
            return None

    adapter = FakeAdapter()
    assert isinstance(adapter, MarketplaceAdapter)

    results = list(adapter.search("bike", 10))
    assert len(results) == 1
    assert all(isinstance(item, Listing) for item in results)

    assert adapter.get_item("1") is not None
    assert adapter.get_item("missing") is None


def test_adapters_are_interchangeable():
    """Both present and future adapters return the same Listing schema."""
    from src.adapters.base import MarketplaceAdapter
    from src.models.listing import Listing

    class AdapterA:
        def search(self, query: str, limit: int) -> Iterable[Listing]:
            return [Listing(id="a", title="a", url="https://example.com/a")]

        def get_item(self, item_id: str) -> Listing | None:
            return Listing(id=item_id, title="a", url="https://example.com/a")

    class AdapterB:
        def search(self, query: str, limit: int) -> Iterable[Listing]:
            return [Listing(id="b", title="b", url="https://example.com/b")]

        def get_item(self, item_id: str) -> Listing | None:
            return None

    for cls in (AdapterA, AdapterB):
        assert isinstance(cls(), MarketplaceAdapter)
        for item in cls().search("q", 5):
            assert isinstance(item, Listing)
            assert isinstance(item.id, str)
            assert isinstance(item.title, str)
            assert isinstance(item.url, str)
