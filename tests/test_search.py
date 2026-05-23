"""ძიების ლოგიკის ტესტები — phone normalization, free_text guard, VIN."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.schemas import SearchRequest
from src.api.search import _build_query, _normalize_phone_query


# ---------------------------------------------------------------------------
# phone normalization — ცუდი input → 9 ციფრი
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("595515141",        "595515141"),    # already clean
    ("+995595515141",    "595515141"),    # joined country code
    ("+995 595 515 141", "595515141"),    # display ფორმატით
    ("+995 595 51 51 41","595515141"),    # 3-2-2-2 grouping
    ("995 595 515 141",  "595515141"),    # no plus
    ("(595) 51-51-41",   "595515141"),    # parentheses + dashes
    ("5-9-5-5-1-5-1-4-1","595515141"),    # absurd dashes
    ("55555 5555",       "555555555"),    # short messy
    ("abc595515141xyz",  "595515141"),    # garbage around
    (" 595 515 141 ",    "595515141"),    # surrounding whitespace
    ("",                 ""),
    ("abc",              ""),
    ("5555",             "5555"),         # 4 ციფრი — passes minimum
])
def test_normalize_phone_query(raw, expected):
    """ნებისმიერი user input → ბოლო 9 ციფრი (ან ნაკლები)."""
    assert _normalize_phone_query(raw) == expected


# ---------------------------------------------------------------------------
# _build_query — ფაქტობრივად endpoint-ის შემავალი validation
# ---------------------------------------------------------------------------

def test_build_query_vin_full():
    """17-ციფრიანი VIN → exact match."""
    sql, params, qtype = _build_query(SearchRequest(vin="WBA1234567890ABCD"))
    assert qtype == "vin"
    assert "vin = %s" in sql
    assert params == ("WBA1234567890ABCD",)


def test_build_query_vin_partial():
    """ნაკლები ციფრები → LIKE-ით prefix match."""
    sql, params, qtype = _build_query(SearchRequest(vin="WBA123"))
    assert qtype == "vin"
    assert "vin LIKE %s" in sql
    assert params == ("WBA123%",)


def test_build_query_phone():
    """ნომერი → ციფრებად, LIKE-ით regexp_replace-ით."""
    sql, params, qtype = _build_query(SearchRequest(phone="+995 595 515 141"))
    assert qtype == "phone"
    assert "regexp_replace(phone" in sql
    assert params == ("%595515141",)


def test_build_query_phone_too_short():
    """4 char-ი მაგრამ 1 ციფრი ნორმალიზაციის შემდეგ — უარყავი."""
    # pydantic-ის min_length=4 გავიდა, მაგრამ ციფრებად 1-ია → reject
    with pytest.raises(HTTPException) as exc:
        _build_query(SearchRequest(phone="abc1"))
    assert exc.value.status_code == 400
    assert "მინიმუმ 4" in exc.value.detail


def test_build_query_free_text_ok():
    """საღი ძიება — წელი/მოდელი/რამე."""
    sql, params, qtype = _build_query(SearchRequest(free_text="Toyota Camry 2020"))
    assert qtype == "free_text"
    assert "similarity" in sql


def test_build_query_free_text_too_generic_single_brand():
    """ერთი სიტყვა „Toyota" — ძალიან ფართო, უარყავი."""
    with pytest.raises(HTTPException) as exc:
        _build_query(SearchRequest(free_text="Toyota"))
    assert exc.value.status_code == 400


def test_build_query_free_text_too_short():
    """4 ასო — ცოტა."""
    with pytest.raises(HTTPException) as exc:
        _build_query(SearchRequest(free_text="bmw"))
    assert exc.value.status_code == 400


def test_build_query_free_text_with_digit_allowed():
    """ერთი სიტყვა + ციფრი (მაგ. 'WBA12345') — სავსებით სპეციფიკურია."""
    sql, _, qtype = _build_query(SearchRequest(free_text="WBA12345"))
    assert qtype == "free_text"


def test_build_query_empty_request():
    """ცარიელი request — უარყავი."""
    with pytest.raises(HTTPException) as exc:
        _build_query(SearchRequest())
    assert exc.value.status_code == 400
