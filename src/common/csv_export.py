# CSV export: a plain archive in exports/, kept alongside the database
#
# File layout is exports/{source}-{YYYY-MM-DD}.csv, one file per source per
# day. A second run on the same day appends and does not repeat the header.
#
# Headers come from Car.model_fields, so autopapa and myauto share one schema.
#
# List fields (image_urls, image_keys) are joined with ";" into a single cell.
# Booleans become "true"/"false"/"", and None becomes an empty string, not "None".

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .config import ROOT_DIR
from .models import Car


EXPORTS_DIR: Path = ROOT_DIR / "exports"

_FIELDS: tuple[str, ...] = tuple(Car.model_fields.keys())


def csv_path(source: str, day: date | None = None) -> Path:
    # path to the file: exports/{source}-{YYYY-MM-DD}.csv
    day = day or date.today()
    return EXPORTS_DIR / f"{source}-{day.isoformat()}.csv"


def _serialize_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ";".join(str(v) for v in value)
    return str(value)


def _car_to_row(car: Car) -> dict[str, str]:
    data = car.model_dump()
    return {field: _serialize_value(data.get(field)) for field in _FIELDS}


def append_cars_to_csv(cars: list[Car], source: str, day: date | None = None) -> int:
    # append a batch; if the file is new, write the header first
    #
    # Returns the number of rows written.
    if not cars:
        return 0

    path = csv_path(source, day)
    path.parent.mkdir(parents=True, exist_ok=True)

    file_exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        for car in cars:
            writer.writerow(_car_to_row(car))

    return len(cars)
