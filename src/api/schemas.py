"""
API-ის request/response მოდელები. Pydantic-ით ვალიდირდება ავტომატურად.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """ძიების მოთხოვნა."""

    query: str | None = Field(None, min_length=1, max_length=200)

    year_from:    int | None = Field(None, ge=1900, le=2030)
    year_to:      int | None = Field(None, ge=1900, le=2030)
    price_from:   int | None = Field(None, ge=0)
    price_to:     int | None = Field(None, ge=0)
    mileage_from: int | None = Field(None, ge=0)
    mileage_to:   int | None = Field(None, ge=0)

    body_type:    str | None = Field(None, max_length=40)
    fuel_type:    str | None = Field(None, max_length=40)
    gearbox:      str | None = Field(None, max_length=40)
    drive_wheels: str | None = Field(None, max_length=40)
    customs_cleared: bool | None = None

    # multi-select filters (new filter UI). The singular fields above are kept
    # for backward compatibility; the server merges both into one IN per column.
    manufacturers: list[str] | None = Field(None, max_length=60)
    models:        list[str] | None = Field(None, max_length=80)
    body_types:    list[str] | None = Field(None, max_length=40)
    fuels:         list[str] | None = Field(None, max_length=40)
    gearboxes:     list[str] | None = Field(None, max_length=40)
    drives:        list[str] | None = Field(None, max_length=40)
    locations:     list[str] | None = Field(None, max_length=60)

    sort: str | None = Field(None, max_length=20)

    page: int = Field(1, ge=1, le=200)

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

    query_type: str
    results: list[CarPublic]
    results_count: int
    total_count: int
    page: int
    page_size: int
    remaining_searches: int | None


class SearchCount(BaseModel):
    """მხოლოდ რაოდენობა — ცოცხალი counter ძიების ღილაკზე."""

    total_count: int


class HealthCheck(BaseModel):
    """რა მუშაობს და რა არა."""

    status: str
    db: bool
    r2: bool
