"""
მონაცემთა მოდელი — ერთი მანქანის სრული აღწერა.

ვიყენებთ pydantic BaseModel-ს, რომ ჩვენ ერთად მივიღოთ:
  - ტიპის შემოწმება (year უნდა იყოს int, ფასი integer და ა.შ.)
  - ცარიელი მნიშვნელობების ნორმალური handling (None vs "")
  - JSON სერიალიზაცია უფასოდ
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Car(BaseModel):
    """ერთი მანქანის სრული ჩანაწერი — იგივე ფორმა PostgreSQL-ისთვისაც."""

    # ----- წყაროს იდენტიფიკაცია -----
    source: str                                     # "autopapa" | "myauto"
    source_id: str                                  # მანქანის id წყაროზე
    url: str

    # ----- ძირითადი -----
    manufacturer: str = ""
    model: str = ""
    year: int | None = None
    body_type: str = ""

    # ----- ფასი -----
    price_amount: int | None = None
    price_currency: str = ""                        # "USD" | "EUR" | "GEL"
    price_with_customs: int | None = None

    # ----- ძრავა და ტრანსმისია -----
    engine_volume_l: float | None = None
    engine_type: str = ""
    cylinders: int | None = None
    power_hp: int | None = None
    has_turbo: bool | None = None
    gearbox: str = ""
    drive_wheels: str = ""

    # ----- გარბენი და გარეგნობა -----
    mileage_km: int | None = None
    color: str = ""
    doors: int | None = None
    seats: int | None = None
    interior_color: str = ""
    interior_material: str = ""

    # ----- სხვა -----
    steering: str = ""                              # "მარცხენა" | "მარჯვენა"
    condition: str = ""
    customs_cleared: bool | None = None
    has_catalyst: bool | None = None
    tech_inspection: bool | None = None

    # ----- იდენტიფიკატორი -----
    vin: str = ""                                   # 17 სიმბოლო, დიდი ასოები
    license_plate: str = ""

    # ----- კონტაქტი -----
    location: str = ""
    seller_name: str = ""
    phone: str = ""                                 # +-ით იწყება

    # ----- მეტა -----
    posted_date: str = ""
    views: int | None = None

    # ----- შინაარსი -----
    description: str = ""

    # ----- მედია -----
    video_url: str = ""
    image_urls: list[str] = Field(default_factory=list)
    image_keys: list[str] = Field(default_factory=list)   # R2-ში uploaded keys
