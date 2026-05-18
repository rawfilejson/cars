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
    """ძიების მოთხოვნა — მინიმუმ ერთი ფილდი უნდა იყოს შევსებული."""

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

    query_type: str                                 # "vin" | "phone" | "free_text"
    results: list[CarPublic]
    results_count: int
    charged: bool                                   # ყოველთვის False (უფასოა)
    remaining_free_searches: int | None             # ამ საათში დარჩენილი ცდები


class HealthCheck(BaseModel):
    """რა მუშაობს და რა არა."""

    status: str
    db: bool
    r2: bool
