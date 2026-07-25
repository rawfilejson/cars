# CSV export — DB-ის გვერდით სუფთა archive-ი exports/ ფოლდერში.
#
# ფაილის სქემა: `exports/{source}-{YYYY-MM-DD}.csv`. ერთი ფაილი per source per
# დღე. ერთიდაიგივე დღეს მეორე ჯერ run-ი — append-ი, header არ იწერება ხელახლა.
#
# Headers — Car.model_fields-დან, ანუ ერთიდაიგივე სქემა autopapa/myauto-სთვის.
#
# list ფილდები (image_urls, image_keys) → `";"` separator-ით (ერთი ცელი).
# bool-ები → "true"/"false"/"". None → ცარიელი string (არა "None").

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .config import ROOT_DIR
from .models import Car


EXPORTS_DIR: Path = ROOT_DIR / "exports"

_FIELDS: tuple[str, ...] = tuple(Car.model_fields.keys())


def csv_path(source: str, day: date | None = None) -> Path:
    # ფაილის ბილიკი — `exports/{source}-{YYYY-MM-DD}.csv`.
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
    # Append batch-ი ფაილში. ფაილი არ არსებობს → headers-ი იწერება ჯერ.
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
