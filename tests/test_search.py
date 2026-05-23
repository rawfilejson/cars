"""ძიების ლოგიკის ტესტები — smart route + legacy + phone normalization."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.schemas import SearchRequest
from src.api.search import _build_query, _normalize_phone_query, _looks_like_phone


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
# _looks_like_phone — phone detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("595515141",          True),    # 9 pure digits
    ("+995 595 515 141",   True),    # 12 digits, 75% digits
    ("5-9-5-5-1-5-1-4-1",  True),    # 9 digits, well over 60%
    ("(555) 51-51-41",     True),
    ("Toyota Camry 2020",  False),   # only 4 digits, 16% digits
    ("Toyota",             False),   # 0 digits
    ("123",                False),   # only 3 digits
    ("123456",             False),   # 6 digits, < 7
    ("1234567",            True),    # 7 digits, 100%
])
def test_looks_like_phone(text, expected):
    assert _looks_like_phone(text) is expected


# ---------------------------------------------------------------------------
# Smart route — single `query` field
# ---------------------------------------------------------------------------

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
    assert "ILIKE" in sql
    assert "similarity" in sql


def test_smart_route_multi_word_AND():
    """Each word gets its own ILIKE clause joined with AND."""
    sql, params, qtype = _build_query(SearchRequest(query="Toyota Camry 2020"))
    assert qtype == "search"
    # 3 ILIKE clauses for 3 words
    assert sql.count("ILIKE") == 3
    # similarity arg first (matches SQL order), then patterns
    assert params == ("Toyota Camry 2020", "%Toyota%", "%Camry%", "%2020%")


def test_smart_route_georgian_query():
    """Georgian text works as a search term."""
    sql, params, qtype = _build_query(SearchRequest(query="თბილისი"))
    assert qtype == "search"
    # params: (text for similarity, then patterns)
    assert params == ("თბილისი", "%თბილისი%")


def test_smart_route_empty_query():
    with pytest.raises(HTTPException) as exc:
        _build_query(SearchRequest(query="   "))
    assert exc.value.status_code == 400


def test_smart_route_single_char_rejected():
    with pytest.raises(HTTPException) as exc:
        _build_query(SearchRequest(query="A"))
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Legacy paths — old frontend (Carba) keeps working
# ---------------------------------------------------------------------------

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
