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
    """Each word gets its own LIKE clause joined with AND.

    Param order: the word patterns come first (the WHERE clause), then the
    similarity-rank text. The two-phase paging CTE references the ORDER BY
    in both the inner and outer SELECT, so the rank text is bound twice.
    """
    sql, params, qtype = _build_query(SearchRequest(query="Toyota Camry 2020"))
    assert qtype == "search"
    assert sql.count("search_blob LIKE") == 3
    assert params[:3] == ("%toyota%", "%camry%", "%2020%")
    assert params[3:] and all(p == "Toyota Camry 2020" for p in params[3:])


def test_smart_route_georgian_query():
    """Georgian text works as a search term. Georgian has no case so
    .lower() is a no-op for these chars."""
    sql, params, qtype = _build_query(SearchRequest(query="თბილისი"))
    assert qtype == "search"
    assert params[0] == "%თბილისი%"
    assert params[1:] and all(p == "თბილისი" for p in params[1:])


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


def test_result_cache_evicts_oldest_not_all():
    """Over capacity the cache drops the OLDEST entries (FIFO/LRU), not the
    whole thing — a full wipe would stampede Supabase on the next burst."""
    from src.api import search as s

    s._RESULT_CACHE.clear()
    try:
        overflow = s._RESULT_CACHE_MAX + 50
        for i in range(overflow):
            s._cache_put(f"k{i}", [i], float(i))
        assert len(s._RESULT_CACHE) == s._RESULT_CACHE_MAX  # capped, not cleared
        assert "k0" not in s._RESULT_CACHE                  # oldest evicted
        assert f"k{overflow - 1}" in s._RESULT_CACHE        # newest retained
    finally:
        s._RESULT_CACHE.clear()


def test_fx_rates_single_source_of_truth():
    """The SQL price-conversion CASE and the Python _clean_price helper must use
    the same FX rates — both derive from config.FX_RATES_TO_USD, never drift."""
    from src.common.config import FX_RATES_TO_USD
    from src.api.search import _PRICE_USD_RAW, _FX_TO_USD

    assert _FX_TO_USD is FX_RATES_TO_USD
    for cur, rate in FX_RATES_TO_USD.items():
        assert f"WHEN '{cur}' THEN price_amount::float * {rate}" in _PRICE_USD_RAW
