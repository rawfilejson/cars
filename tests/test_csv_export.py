"""CSV export-ის ტესტები — header, append, list/bool/null handling."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import pytest

from src.common import csv_export
from src.common.models import Car


@pytest.fixture
def temp_exports(monkeypatch):
    """ცალკე ფოლდერი ყოველი ტესტისთვის, რომ რეალური exports/-ი არ გავაჭუჭყიანოთ."""
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(csv_export, "EXPORTS_DIR", Path(tmp))
        yield Path(tmp)


def make_car(**overrides) -> Car:
    defaults = dict(
        source="myauto",
        source_id="123",
        url="https://www.myauto.ge/ka/pr/123/sale",
        manufacturer="Lexus",
        model="ES 350",
        year=2014,
        price_amount=27290,
        price_currency="GEL",
        phone="+995 595 515 141",
        image_urls=["https://example.com/1.jpg", "https://example.com/2.jpg"],
        customs_cleared=True,
    )
    defaults.update(overrides)
    return Car(**defaults)


def test_creates_file_with_header(temp_exports):
    """პირველი append-ი → header + 1 row."""
    car = make_car()
    written = csv_export.append_cars_to_csv([car], "myauto")
    assert written == 1

    files = list(temp_exports.glob("myauto-*.csv"))
    assert len(files) == 1

    with files[0].open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["manufacturer"] == "Lexus"
    assert rows[0]["price_amount"] == "27290"


def test_appends_without_duplicating_header(temp_exports):
    """ერთიდაიგივე ფაილში მე-2 batch — header-ი არ მეორდება."""
    csv_export.append_cars_to_csv([make_car(source_id="1")], "myauto")
    csv_export.append_cars_to_csv([make_car(source_id="2")], "myauto")

    files = list(temp_exports.glob("myauto-*.csv"))
    with files[0].open(encoding="utf-8") as f:
        lines = f.readlines()

    # ერთი header + ორი data row = 3 ხაზი
    assert len(lines) == 3
    assert lines[0].startswith("source,source_id,url")


def test_list_fields_joined_with_semicolons(temp_exports):
    """image_urls სია → "url1;url2;url3" ერთ უჯრედში."""
    car = make_car(image_urls=["a.jpg", "b.jpg", "c.jpg"])
    csv_export.append_cars_to_csv([car], "myauto")

    files = list(temp_exports.glob("myauto-*.csv"))
    with files[0].open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row = next(reader)
    assert row["image_urls"] == "a.jpg;b.jpg;c.jpg"


def test_bool_fields_serialized(temp_exports):
    """bool ფილდები — "true"/"false", None → ცარიელი."""
    csv_export.append_cars_to_csv([
        make_car(customs_cleared=True, has_turbo=False, tech_inspection=None),
    ], "myauto")

    files = list(temp_exports.glob("myauto-*.csv"))
    with files[0].open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row = next(reader)
    assert row["customs_cleared"] == "true"
    assert row["has_turbo"] == "false"
    assert row["tech_inspection"] == ""


def test_none_fields_empty_string(temp_exports):
    """None → ცარიელი string, არა "None"."""
    car = make_car(year=None, price_amount=None)
    csv_export.append_cars_to_csv([car], "myauto")

    files = list(temp_exports.glob("myauto-*.csv"))
    with files[0].open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row = next(reader)
    assert row["year"] == ""
    assert row["price_amount"] == ""


def test_empty_batch_does_nothing(temp_exports):
    """ცარიელი list-ი → 0 row, ფაილი არ იქმნება."""
    written = csv_export.append_cars_to_csv([], "myauto")
    assert written == 0
    assert not list(temp_exports.glob("*.csv"))


def test_path_per_source_and_date(temp_exports):
    """ფაილი ცალკეა autopapa/myauto-სთვის."""
    csv_export.append_cars_to_csv([make_car(source="myauto")], "myauto")
    csv_export.append_cars_to_csv([make_car(source="autopapa")], "autopapa")

    paths = sorted(p.name.split("-")[0] for p in temp_exports.glob("*.csv"))
    assert paths == ["autopapa", "myauto"]
