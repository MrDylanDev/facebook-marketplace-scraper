"""Streaming SQLite exporter for marketplace listings (Unit 3 slice).

Consumes ``Iterable[Listing]`` in a single pass — safe for generators and
large result sets. Creates the ``listings`` table when missing and appends
rows. Stdlib only.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from src.models.listing import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    price TEXT,
    currency TEXT,
    url TEXT NOT NULL,
    image_url TEXT,
    seller TEXT,
    location TEXT
)
"""

INSERT = """
INSERT OR REPLACE INTO listings
    (id, title, price, currency, url, image_url, seller, location)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


def listing_to_tuple(listing: Listing) -> tuple:
    """Map a Listing to a SQLite row tuple (Decimal price stored as TEXT)."""
    return (
        listing.id,
        listing.title,
        None if listing.price is None else str(listing.price),
        listing.currency,
        listing.url,
        listing.image_url,
        listing.seller,
        listing.location,
    )


def export_sqlite(listings: Iterable[Listing], path: str | Path) -> int:
    """Append listings to the ``listings`` table at ``path``.

    Returns the number of rows written.
    """
    count = 0
    conn = sqlite3.connect(path)
    try:
        conn.execute(SCHEMA)
        for listing in listings:
            conn.execute(INSERT, listing_to_tuple(listing))
            count += 1
        conn.commit()
    finally:
        conn.close()
    return count
