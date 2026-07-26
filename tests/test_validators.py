# validate_car() tests - every range and rule has at least one positive + negative case

from __future__ import annotations

import pytest

from src.common.models import Car
from src.common.validators import validate_car


def make_car(**overrides) -> Car:
    defaults = dict(
        source="autopapa",
        source_id="123",
        url="https://autopapa.ge/ge/123",
        manufacturer="Toyota",
        model="Camry",
        year=2018,
        price_amount=15000,
        price_currency="USD",
        mileage_km=80000,
        engine_volume_l=2.5,
        power_hp=180,
        cylinders=4,
        doors=4,
        seats=5,
        vin="JTNBE46K473012345",
        phone="+995 595 515 141",
    )
    defaults.update(overrides)
    return Car(**defaults)


def test_clean_car_has_no_issues():
    assert validate_car(make_car()) == []


def test_year_out_of_range():
    assert "year 1850" in validate_car(make_car(year=1850))[0]
    assert "year 2099" in validate_car(make_car(year=2099))[0]


def test_year_none_is_fine():
    assert validate_car(make_car(year=None)) == []


def test_price_zero_or_negative():
    assert any("price_amount" in i for i in validate_car(make_car(price_amount=0)))
    assert any("price_amount" in i for i in validate_car(make_car(price_amount=-100)))


def test_price_absurdly_high():
    assert any("too high" in i for i in validate_car(make_car(price_amount=99_999_999)))


def test_price_currency_invalid():
    issues = validate_car(make_car(price_currency="BTC"))
    assert any("price_currency" in i for i in issues)


def test_mileage_out_of_range():
    assert any("mileage" in i for i in validate_car(make_car(mileage_km=-1)))
    assert any("mileage" in i for i in validate_car(make_car(mileage_km=5_000_000)))


def test_engine_volume_out_of_range():
    assert any(
        "engine_volume_l" in i for i in validate_car(make_car(engine_volume_l=0.05))
    )
    assert any(
        "engine_volume_l" in i for i in validate_car(make_car(engine_volume_l=20.0))
    )


def test_power_hp_out_of_range():
    assert any("power_hp" in i for i in validate_car(make_car(power_hp=0)))
    assert any("power_hp" in i for i in validate_car(make_car(power_hp=5000)))


def test_vin_wrong_length():
    bad_vin = "JTNBE46K47"
    issues = validate_car(make_car(vin=bad_vin))
    assert any("vin" in i and "length" in i for i in issues)


def test_vin_empty_is_fine():
    assert validate_car(make_car(vin="")) == []


def test_phone_must_start_with_plus():
    issues = validate_car(make_car(phone="595515141"))
    assert any("phone" in i and "+" in i for i in issues)


def test_phone_empty_is_fine():
    assert validate_car(make_car(phone="")) == []


def test_missing_required_fields():
    issues = validate_car(make_car(source="", source_id="", url=""))
    assert any("source" in i for i in issues)
    assert any("source_id" in i for i in issues)
    assert any("url" in i for i in issues)


@pytest.mark.parametrize(
    "field,bad,good",
    [
        ("cylinders", 20, 6),
        ("doors", 15, 4),
        ("seats", 100, 5),
    ],
)
def test_simple_int_ranges(field, bad, good):
    assert validate_car(make_car(**{field: bad})) != []
    assert validate_car(make_car(**{field: good})) == []
