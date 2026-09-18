"""Marketplace adapter contract."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from src.models.listing import Listing


@runtime_checkable
class MarketplaceAdapter(Protocol):
    """Pluggable target contract: MercadoLibre, Facebook, or test fakes."""

    def search(self, query: str, limit: int) -> Iterable[Listing]:
        """Search listings matching query, up to limit results."""
        ...

    def get_item(self, item_id: str) -> Listing | None:
        """Fetch a single listing by id, or None when not found."""
        ...
