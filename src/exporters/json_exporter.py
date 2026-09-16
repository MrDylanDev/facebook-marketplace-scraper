"""Streaming JSON exporter for marketplace listings (Unit 3 slice).

Consumes ``Iterable[Listing]`` in a single pass — safe for generators and
large result sets. Writes a top-level JSON array incrementally so listings
are never all materialized in memory. Stdlib only.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from src.models.listing import Listing


def listing_to_dict(listing: Listing) -> dict:
    """Map a Listing to a JSON-serializable dict (Decimal price as string)."""
    return {
        "id": listing.id,
        "title": listing.title,
        "price": None if listing.price is None else str(listing.price),
        "currency": listing.currency,
        "url": listing.url,
        "image_url": listing.image_url,
        "seller": listing.seller,
        "location": listing.location,
    }


def export_json(listings: Iterable[Listing], path: str | Path) -> int:
    """Write listings to ``path`` as a JSON array. Returns items written."""
    count = 0
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("[")
        first = True
        for listing in listings:
            if not first:
                fh.write(",")
            fh.write(json.dumps(listing_to_dict(listing), ensure_ascii=False))
            first = False
            count += 1
        fh.write("]")
    return count
