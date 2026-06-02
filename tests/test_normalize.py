"""normalize.py-ის ტესტები — phone, price, engine volume, customs."""

from __future__ import annotations

import pytest

from src.common.normalize import (
    clean_engine_volume,
    clean_int,
    format_phone,
    normalize_steering,
    parse_bool_yes_no,
    parse_customs,
    sane_int,
    split_price,
)


GE = "+995 595 515 141"


@pytest.mark.parametrize("raw", [
    "595515141",
    "+995595515141",
    "+995 595 51 51 41",
    "+995 595 515 141",
    "tel:+995595515141",
    "tel:+995 595 51 51 41",
    "  595515141  ",
    "595-51-51-41",
    "595.51.51.41",
    "(595) 51 51 41",
    "5-9-5-5-1-5-1-4-1",
    "5 9 5 5 1 5 1 4 1",
    "abc595515141xyz",
    "995595515141",
])
def test_format_phone_ge_variants(raw):
    """ნებისმიერი ცუდი ფორმატი ქართული მობილურისთვის → ერთიდაიგივე canonical."""
    assert format_phone(raw) == GE


@pytest.mark.parametrize("raw", ["", None, "abc", "---", "()", " "])
def test_format_phone_empty(raw):
    """ცარიელი / არასწორი input → ცარიელი string."""
    assert format_phone(raw) == ""


def test_format_phone_russian():
    """რუსული 11-ციფრიანი ნომერი → +7 ფორმატით."""
    assert format_phone("+79161234567") == "+7 916 123 45 67"
    assert format_phone("7 916 123 45 67") == "+7 916 123 45 67"


def test_format_phone_landline_3():
    """თბილისის ლანდლაინი — 9 ციფრი, 3-ით იწყება."""
    assert format_phone("322 12 34 56") == "+995 322 123 456"


def test_format_phone_unknown_keeps_digits():
    """უცნობი ფორმატი — +-ით + ციფრებით (არასოდეს ვკარგავთ ციფრებს)."""
    assert format_phone("12345") == "+12345"


@pytest.mark.parametrize("raw,expected", [
    ("26 000 კმ", 26000),
    ("$11 500", 11500),
    ("2014", 2014),
    ("", None),
    (None, None),
    ("abc", None),
    ("173000 km", 173000),
])
def test_clean_int(raw, expected):
    assert clean_int(raw) == expected


@pytest.mark.parametrize("raw,lo,hi,expected", [
    ("180 ც.ძ.", 1, 2000, 180),
    ("2490 ც.ძ.", 1, 2000, None),
    ("0", 1, 2000, None),
    ("", 1, 2000, None),
    (None, 1, 2000, None),
    ("abc", 1, 2000, None),
    ("6", 1, 16, 6),
    ("32", 1, 16, None),
])
def test_sane_int(raw, lo, hi, expected):
    assert sane_int(raw, lo, hi) == expected


@pytest.mark.parametrize("raw,amount,currency", [
    ("$11 500", 11500, "USD"),
    ("€9 500", 9500, "EUR"),
    ("₾35 000", 35000, "GEL"),
    ("35000 ლარი", 35000, "GEL"),
    ("9500 EUR", 9500, "EUR"),
    ("", None, ""),
    (None, None, ""),
    ("11500", 11500, ""),
])
def test_split_price(raw, amount, currency):
    assert split_price(raw) == (amount, currency)


@pytest.mark.parametrize("raw,expected", [
    ("2.5 ლ", 2.5),
    ("2,5", 2.5),
    ("3.5", 3.5),
    ("1499", 1.5),
    ("1600 cc", 1.6),
    ("0", None),
    ("99999", None),
    ("", None),
    (None, None),
])
def test_clean_engine_volume(raw, expected):
    assert clean_engine_volume(raw) == expected


def test_normalize_steering():
    assert normalize_steering("ABS, მარცხენა საჭე, ESP") == "მარცხენა"
    assert normalize_steering("მარჯვენა, კონდიც.") == "მარჯვენა"
    assert normalize_steering("") == ""
    assert normalize_steering(None) == ""
    assert normalize_steering("რაღაც სხვა") == ""


def test_parse_customs():
    assert parse_customs("განბაჟებული") is True
    assert parse_customs("განუბაჟებელი") is False
    assert parse_customs("") is None
    assert parse_customs(None) is None


def test_parse_bool_yes_no():
    assert parse_bool_yes_no("კი") is True
    assert parse_bool_yes_no("დიახ") is True
    assert parse_bool_yes_no("არა") is False
    assert parse_bool_yes_no("") is None
    assert parse_bool_yes_no(None) is None
    assert parse_bool_yes_no("რაღაც") is None
