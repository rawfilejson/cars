"""ძიების ლოგიკის ტესტები — smart route + legacy + phone normalization."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.schemas import SearchRequest
from src.api.search import _build_query, _normalize_phone_query, _looks_like_phone


@pytest.mark.parametrize("raw,expected", [
    ("595515141",        "595515141"),
    ("+995595515141",    "595515141"),
    ("+995 595 515 141", "595515141"),
    ("+995 595 51 51 41","595515141"),
    ("995 595 515 141",  "595515141"),
    ("(595) 51-51-41",   "595515141"),
    ("5-9-5-5-1-5-1-4-1","595515141"),
    ("55555 5555",       "555555555"),
    ("abc595515141xyz",  "595515141"),
    (" 595 515 141 ",    "595515141"),
    ("",                 ""),
    ("abc",              ""),
    ("5555",             "5555"),
])
def test_normalize_phone_query(raw, expected):
    """ნებისმიერი user input → ბოლო 9 ციფრი (ან ნაკლები)."""
    assert _normalize_phone_query(raw) == expected


@pytest.mark.parametrize("text,expected", [
    ("595515141",          True),
    ("+995 595 515 141",   True),
    ("5-9-5-5-1-5-1-4-1",  True),
    ("(555) 51-51-41",     True),
    ("Toyota Camry 2020",  False),
    ("Toyota",             False),
    ("123",                False),
    ("123456",             False),
    ("1234567",            True),
])
def test_looks_like_phone(text, expected):
    assert _looks_like_phone(text) is expected


def test_smart_route_vin_exact():
    sql, params, qtype = _build_query(SearchRequest(query="WBA1234567890ABCD"))
    assert qtype == "vin"
    assert "vin = %s" in sql
    assert params == ("WBA1234567890ABCD",)


def test_smart_route_vin_lowercase_uppercased():
    """user can type lowercase, we uppercase before matching."""
    sql, params, qtype = _build_query(SearchRequest(query="wba1234567890abcd"))
    assert qtype == "vin"
    assert params == ("WBA1234567890ABCD",)


def test_smart_route_phone():
    sql, params, qtype = _build_query(SearchRequest(query="+995 595 515 141"))
    assert qtype == "phone"
    assert "regexp_replace(phone" in sql
    assert params == ("%595515141",)


def test_smart_route_short_text_ok():
    """Single-word brand search is fine — Ctrl-F semantics."""
    sql, params, qtype = _build_query(SearchRequest(query="Toyota"))
    assert qtype == "search"
    assert "search_blob LIKE" in sql
    assert "similarity" in sql


def test_smart_route_multi_word_AND():
    """Each word gets its own LIKE clause joined with AND."""
    sql, params, qtype = _build_query(SearchRequest(query="Toyota Camry 2020"))
    assert qtype == "search"
    assert sql.count("search_blob LIKE") == 3
    assert params == ("Toyota Camry 2020", "%toyota%", "%camry%", "%2020%")


def test_smart_route_georgian_query():
    """Georgian text works as a search term. Georgian has no case so
    .lower() is a no-op for these chars."""
    sql, params, qtype = _build_query(SearchRequest(query="თბილისი"))
    assert qtype == "search"
    assert params == ("თბილისი", "%თბილისი%")


def test_smart_route_empty_query():
    with pytest.raises(HTTPException) as exc:
        _build_query(SearchRequest(query="   "))
    assert exc.value.status_code == 400


def test_smart_route_single_char_rejected():
    with pytest.raises(HTTPException) as exc:
        _build_query(SearchRequest(query="A"))
    assert exc.value.status_code == 400


def test_legacy_vin_full():
    sql, params, qtype = _build_query(SearchRequest(vin="WBA1234567890ABCD"))
    assert qtype == "vin"
    assert "vin = %s" in sql
    assert params == ("WBA1234567890ABCD",)


def test_legacy_vin_partial():
    sql, params, qtype = _build_query(SearchRequest(vin="WBA123"))
    assert qtype == "vin"
    assert "vin LIKE %s" in sql


def test_legacy_phone():
    sql, params, qtype = _build_query(SearchRequest(phone="+995 595 515 141"))
    assert qtype == "phone"
    assert params == ("%595515141",)


def test_legacy_phone_too_short():
    with pytest.raises(HTTPException) as exc:
        _build_query(SearchRequest(phone="abc1"))
    assert exc.value.status_code == 400


def test_legacy_free_text_routes_to_smart():
    """Legacy free_text just delegates to smart route."""
    sql, _, qtype = _build_query(SearchRequest(free_text="Toyota Camry 2020"))
    assert qtype == "search"


def test_empty_request_rejected():
    with pytest.raises(HTTPException) as exc:
        _build_query(SearchRequest())
    assert exc.value.status_code == 400
