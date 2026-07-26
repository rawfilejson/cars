# The `Car` model - one row in our database, one listing on the source site.

from __future__ import annotations

from pydantic import BaseModel, Field


class Car(BaseModel):
    source: str
    source_id: str
    url: str

    manufacturer: str = ""
    model: str = ""
    year: int | None = None
    body_type: str = ""

    price_amount: int | None = None
    price_currency: str = ""
    price_with_customs: int | None = None

    engine_volume_l: float | None = None
    engine_type: str = ""
    cylinders: int | None = None
    power_hp: int | None = None
    has_turbo: bool | None = None
    gearbox: str = ""
    drive_wheels: str = ""

    mileage_km: int | None = None
    color: str = ""
    doors: int | None = None
    seats: int | None = None
    interior_color: str = ""
    interior_material: str = ""

    steering: str = ""
    condition: str = ""
    customs_cleared: bool | None = None
    has_catalyst: bool | None = None
    tech_inspection: bool | None = None

    vin: str = ""
    license_plate: str = ""

    location: str = ""
    seller_name: str = ""
    phone: str = ""

    posted_date: str = ""
    views: int | None = None

    description: str = ""

    video_url: str = ""
    image_urls: list[str] = Field(default_factory=list)
    image_keys: list[str] = Field(default_factory=list)
