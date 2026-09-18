"""Facebook Marketplace scraper (portfolio demo)."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class Listing(BaseModel):
    """Structured listing shared by all marketplace adapters."""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    price: Decimal | None = None
    currency: str | None = None
    url: str = Field(min_length=1)
    image_url: str | None = None
    seller: str | None = None
    location: str | None = None
