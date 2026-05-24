"""
API-ის request/response მოდელები. Pydantic-ით ვალიდირდება ავტომატურად.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    """ძიების მოთხოვნა."""

    query: str | None = Field(None, min_length=1, max_length=200)

    # range filters (apply on top of query)
    year_from:    int | None = Field(None, ge=1900, le=2030)
    year_to:      int | None = Field(None, ge=1900, le=2030)
    price_from:   int | None = Field(None, ge=0)
    price_to:     int | None = Field(None, ge=0)
    mileage_from: int | None = Field(None, ge=0)
    mileage_to:   int | None = Field(None, ge=0)

    # sort key. Default: newest first.
    # "newest" | "price_asc" | "price_desc" | "year_desc" | "year_asc" |
    # "mileage_asc" | "mileage_desc"
    sort: str | None = Field(None, max_length=20)

    # Pagination — 25 results per page
    page: int = Field(1, ge=1, le=200)

    # Legacy fields — deprecated, kept for backward compatibility
    vin: str | None = Field(None, min_length=3, max_length=17)
    phone: str | None = Field(None, min_length=4, max_length=20)
    free_text: str | None = Field(None, min_length=3, max_length=200)


class CarPublic(BaseModel):
    """ერთი მანქანის public ფორმა — რას ვაჩვენებთ მომხმარებელს."""

    id: int
    source: str
    source_id: str
    url: str

    manufacturer: str
    model: str
    year: int | None
    body_type: str

    price_amount: int | None
    price_currency: str
    price_with_customs: int | None

    engine_volume_l: float | None
    engine_type: str
    power_hp: int | None
    gearbox: str
    drive_wheels: str
    mileage_km: int | None
    color: str
    steering: str
    customs_cleared: bool | None

    vin: str
    location: str
    seller_name: str
    phone: str

    description: str
    video_url: str
    image_urls: list[str]
    image_keys: list[str]

    created_at: datetime
    updated_at: datetime


class SearchResponse(BaseModel):
    """ძიების შედეგი."""

    query_type: str                                 # "vin" | "phone" | "search" | "browse"
    results: list[CarPublic]
    results_count: int                              # rows on THIS page
    total_count: int                                # rows across all pages
    page: int                                       # current page (1-based)
    page_size: int                                  # rows per page
    charged: bool                                   # ყოველთვის False (უფასოა)
    remaining_free_searches: int | None             # ამ საათში დარჩენილი ცდები


class HealthCheck(BaseModel):
    """რა მუშაობს და რა არა."""

    status: str
    db: bool
    r2: bool
