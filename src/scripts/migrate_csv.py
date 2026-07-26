# migrate the old CSV dumps into postgres
# two layouts, told apart by the header. the old AutoPapa.csv keeps photos in one
# comma-separated Media column, the newer MyAuto.csv splits them into Image_1..Image_20
# phone numbers in the old AutoPapa.csv were mangled into scientific notation like
# 9.96E+11 and cannot be recovered, so phone stays empty and the next parser run fills it
#     python -m src.scripts.migrate_csv --file AutoPapa.csv --source autopapa

from __future__ import annotations

import argparse
import csv
from typing import Iterable

from src.common.db import upsert_cars
from src.common.models import Car
from src.common.normalize import (
    clean_engine_volume,
    clean_int,
    clean_text,
    format_phone,
    normalize_steering,
    parse_customs,
    split_price,
)
from src.common.vin import find_vin


csv.field_size_limit(10 * 1024 * 1024)


def _detect_format(header: list[str]) -> str:
    # work out the format from the header fields
    #
    # format B puts photos in separate Image_1, Image_2... columns,
    # while format A has them comma-separated in a single Media column.
    columns = {h.strip().lower() for h in header}
    if "image_1" in columns:
        return "B"
    if "media" in columns:
        return "A"
    raise ValueError(f"unrecognised CSV format, fields were: {header}")


def _row_to_car_format_a(row: dict[str, str], source: str) -> Car | None:
    source_id = (row.get("ID") or "").strip()
    if not source_id:
        return None

    price_raw = row.get("Price", "")
    price_amount, price_currency = split_price(price_raw)

    media_raw = row.get("Media", "") or ""
    image_urls = [u.strip() for u in media_raw.split(",") if u.strip()]

    description = clean_text(row.get("Description", ""))

    vin = find_vin(row.get("VIN", "")) or find_vin(description)

    return Car(
        source=source,
        source_id=source_id,
        url=row.get("URL", "") or "",
        manufacturer=row.get("Manufacturer", "") or "",
        model=row.get("Model", "") or "",
        year=clean_int(row.get("Year", "")),
        price_amount=price_amount,
        price_currency=price_currency,
        engine_volume_l=clean_engine_volume(row.get("Engine_Volume", "")),
        engine_type=row.get("Engine_Type", "") or "",
        mileage_km=clean_int((row.get("Mileage", "") or "").split("/")[0]),
        steering=normalize_steering(row.get("Steering", "")),
        customs_cleared=parse_customs(row.get("Customs", "")),
        vin=vin,
        phone="",
        description=description,
        image_urls=image_urls,
    )


def _row_to_car_format_b(row: dict[str, str], source: str) -> Car | None:
    source_id = (row.get("ID") or "").strip()
    if not source_id:
        return None

    image_urls = []
    for i in range(1, 21):
        url = (row.get(f"Image_{i}") or "").strip()
        if url:
            image_urls.append(url)

    description = clean_text(row.get("Description", ""))
    vin = find_vin(row.get("VIN", "")) or find_vin(description)

    def _b(text: str | None) -> bool | None:
        if not text:
            return None
        text = text.strip().upper()
        if text in ("TRUE", "1", "YES", "კი", "დიახ"):
            return True
        if text in ("FALSE", "0", "NO", "არა"):
            return False
        return None

    customs_raw = row.get("Customs_Cleared", "")
    customs_cleared = parse_customs(customs_raw)
    if customs_cleared is None:
        customs_cleared = _b(customs_raw)

    return Car(
        source=row.get("Source", source) or source,
        source_id=source_id,
        url=row.get("URL", "") or "",
        manufacturer=row.get("Manufacturer", "") or "",
        model=row.get("Model", "") or "",
        year=clean_int(row.get("Year", "")),
        body_type=row.get("Body_Type", "") or "",
        price_amount=clean_int(row.get("Price", "")),
        price_currency=row.get("Currency", "") or "",
        price_with_customs=clean_int(row.get("Price_With_Customs", "")),
        engine_volume_l=clean_engine_volume(row.get("Engine_Volume_L", "")),
        engine_type=row.get("Engine_Type", "") or "",
        cylinders=clean_int(row.get("Cylinders", "")),
        power_hp=clean_int(row.get("Power_HP", "")),
        has_turbo=_b(row.get("Has_Turbo")),
        gearbox=row.get("Gearbox", "") or "",
        drive_wheels=row.get("Drive_Wheels", "") or "",
        mileage_km=clean_int(row.get("Mileage_KM", "")),
        color=row.get("Color", "") or "",
        doors=clean_int(row.get("Doors", "")),
        seats=clean_int(row.get("Seats", "")),
        interior_color=row.get("Interior_Color", "") or "",
        interior_material=row.get("Interior_Material", "") or "",
        steering=normalize_steering(row.get("Steering", "")),
        condition=row.get("Condition", "") or "",
        customs_cleared=customs_cleared,
        has_catalyst=_b(row.get("Has_Catalyst")),
        tech_inspection=_b(row.get("Tech_Inspection")),
        vin=vin,
        license_plate=row.get("License_Plate", "") or "",
        location=row.get("Location", "") or "",
        seller_name=row.get("Seller_Name", "") or "",
        phone=format_phone(row.get("Phone", "")),
        posted_date=row.get("Posted_Date", "") or "",
        views=clean_int(row.get("Views", "")),
        description=description,
        video_url=row.get("Video_1", "") or "",
        image_urls=image_urls,
    )


def _iter_cars(path: str, source: str) -> Iterable[Car]:
    # iterate Car objects out of one file
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("empty CSV file")

        fmt = _detect_format(list(reader.fieldnames))
        convert = _row_to_car_format_a if fmt == "A" else _row_to_car_format_b
        print(f"  format: {fmt}")

        for row in reader:
            try:
                car = convert(row, source)
            except Exception as exc:
                print(f"  [SKIP] {row.get('ID')} - {exc}")
                continue
            if car is not None:
                yield car


async def main() -> None:
    parser = argparse.ArgumentParser(description="migrate a CSV dump into PostgreSQL")
    parser.add_argument("--file", required=True, help="path to the CSV file")
    parser.add_argument(
        "--source", required=True, help="source name (autopapa/myauto)"
    )
    parser.add_argument(
        "--batch", type=int, default=500, help="how many rows to write per batch"
    )
    args = parser.parse_args()

    print(f"migrating {args.file} -> database (source = {args.source})")

    buffer = []
    total = saved = 0

    for car in _iter_cars(args.file, args.source):
        buffer.append(car)
        total += 1

        if len(buffer) >= args.batch:
            saved += await upsert_cars(buffer)
            buffer.clear()
            print(f"  {saved}/{total} written...")

    if buffer:
        saved += await upsert_cars(buffer)

    print(f"\ndone, wrote {saved}/{total} cars")


if __name__ == "__main__":
    from src.common.runtime import run

    run(main())
