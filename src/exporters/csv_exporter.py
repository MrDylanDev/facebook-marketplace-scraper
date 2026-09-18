"""Streaming CSV exporter for marketplace listings (Unit 3 slice).

Consumes ``Iterable[Listing]`` in a single pass — safe for generators and
large result sets. Stdlib only.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

from src.models.listing import Listing

FIELDNAMES = (
    "id",
    "title",
    "price",
    "currency",
    "url",
    "image_url",
    "seller",
    "location",
)


def listing_to_row(listing: Listing) -> dict[str, str]:
    """Map a Listing to a flat CSV row (None becomes empty string)."""
    return {
        "id": listing.id,
        "title": listing.title,
        "price": "" if listing.price is None else str(listing.price),
        "currency": listing.currency or "",
        "url": listing.url,
        "image_url": listing.image_url or "",
        "seller": listing.seller or "",
        "location": listing.location or "",
    }


def export_csv(listings: Iterable[Listing], path: str | Path) -> int:
    """Write listings to ``path`` as CSV. Returns the number of rows written."""
    count = 0
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        for listing in listings:
            writer.writerow(listing_to_row(listing))
            count += 1
    return count
