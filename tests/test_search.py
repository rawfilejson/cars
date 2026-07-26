# Tests for the search logic: smart routing, the legacy fields, phone normalisation

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.schemas import SearchRequest
from src.api.search import (
    _build_query,
    _count_where,
    _normalize_phone_query,
    _looks_like_phone,
)


def _build_filter_only(**kwargs):
    # Build a SearchRequest from kwargs and return its (fragments, params)
    from src.api.search import _filter_clauses

    return _filter_clauses(SearchRequest(**kwargs))


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("595515141", "595515141"),
        ("+995595515141", "595515141"),
        ("+995 595 515 141", "595515141"),
        ("+995 595 51 51 41", "595515141"),
        ("995 595 515 141", "595515141"),
        ("(595) 51-51-41", "595515141"),
        ("5-9-5-5-1-5-1-4-1", "595515141"),
        ("55555 5555", "555555555"),
        ("abc595515141xyz", "595515141"),
        (" 595 515 141 ", "595515141"),
        ("", ""),
        ("abc", ""),
        ("5555", "5555"),
    ],
)
def test_normalize_phone_query(raw, expected):
    # any user input reduces to the last 9 digits, or fewer
    assert _normalize_phone_query(raw) == expected


def test_count_where_filters_only():
    where, params = _count_where(SearchRequest(manufacturers=["Toyota"]))
    assert "lower(manufacturer) IN (%s)" in where
    assert params == ("toyota",)


def test_count_where_text_query_applies_words_and_filters():
    # A freeform query must be counted (word LIKEs) together with the filters
    where, params = _count_where(SearchRequest(query="camry", manufacturers=["Toyota"]))
    assert "search_blob LIKE %s" in where
    assert "lower(manufacturer) IN (%s)" in where
    assert params == ("%camry%", "toyota")


def test_count_where_vin_query():
    where, params = _count_where(SearchRequest(query="JT2BF22K1W0123456"))
    assert where.startswith("vin = %s")
    assert params == ("JT2BF22K1W0123456",)


def test_count_where_empty_still_hides_gone_listings():
    # with nothing to filter on the count is every live row, not every row
    where, params = _count_where(SearchRequest())
    assert where == "gone_at IS NULL"
    assert params == ()


def test_count_where_vin_ignores_gone_at():
    # a VIN lookup is the archive query, a sold car still has to come back
    where, _ = _count_where(SearchRequest(query="JT2BF22K1W0123456"))
    assert "gone_at" not in where


def test_count_where_text_hides_gone_listings():
    where, _ = _count_where(SearchRequest(query="camry"))
    assert "gone_at IS NULL" in where


@pytest.mark.parametrize(
    "text,expected",
    [
        ("595515141", True),
        ("+995 595 515 141", True),
        ("5-9-5-5-1-5-1-4-1", True),
        ("(555) 51-51-41", True),
        ("Toyota Camry 2020", False),
        ("Toyota", False),
        ("123", False),
        ("123456", False),
        ("1234567", True),
    ],
)
def test_looks_like_phone(text, expected):
    assert _looks_like_phone(text) is expected


def test_smart_route_vin_exact():
    sql, params, qtype = _build_query(SearchRequest(query="WBA1234567890ABCD"))
    assert qtype == "vin"
    assert "vin = %s" in sql
    assert params == ("WBA1234567890ABCD",)


def test_smart_route_vin_lowercase_uppercased():
    # user can type lowercase, we uppercase before matching
    sql, params, qtype = _build_query(SearchRequest(query="wba1234567890abcd"))
    assert qtype == "vin"
    assert params == ("WBA1234567890ABCD",)


def test_smart_route_phone():
    sql, params, qtype = _build_query(SearchRequest(query="+995 595 515 141"))
    assert qtype == "phone"
    assert "regexp_replace(phone" in sql
    assert params == ("%595515141",)


def test_smart_route_short_text_ok():
    # Single-word brand search is fine Ctrl-F semantics
    sql, params, qtype = _build_query(SearchRequest(query="Toyota"))
    assert qtype == "search"
    assert "search_blob LIKE" in sql
    assert "similarity" in sql


def test_smart_route_multi_word_AND():
    # Each word gets its own LIKE clause joined with AND

    # param order: the word patterns come first (the WHERE clause), then the similarity-rank text
    # the two-phase paging CTE references the ORDER BY
    # in both the inner and outer SELECT, so the rank text is bound twice
    sql, params, qtype = _build_query(SearchRequest(query="Toyota Camry 2020"))
    assert qtype == "search"
    assert sql.count("search_blob LIKE") == 3
    assert params[:3] == ("%toyota%", "%camry%", "%2020%")
    assert params[3:] and all(p == "Toyota Camry 2020" for p in params[3:])


def test_smart_route_georgian_query():
    # Georgian text works as a search term
    # Georgian has no case so
    # .lower() is a no-op for these chars.
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
    # Legacy free_text just delegates to smart route.
    sql, _, qtype = _build_query(SearchRequest(free_text="Toyota Camry 2020"))
    assert qtype == "search"


def test_empty_request_rejected():
    with pytest.raises(HTTPException) as exc:
        _build_query(SearchRequest())
    assert exc.value.status_code == 400


def test_result_cache_evicts_oldest_not_all():
    # Over capacity the cache drops the OLDEST entries (FIFO/LRU), not the whole thing - a full wipe would stampede Supabase on the next burst
    from src.api import search as s

    s._RESULT_CACHE.clear()
    try:
        overflow = s._RESULT_CACHE_MAX + 50
        for i in range(overflow):
            s._cache_put(f"k{i}", [i], float(i))
        assert len(s._RESULT_CACHE) == s._RESULT_CACHE_MAX  # capped, not cleared
        assert "k0" not in s._RESULT_CACHE  # oldest evicted
        assert f"k{overflow - 1}" in s._RESULT_CACHE  # newest retained
    finally:
        s._RESULT_CACHE.clear()


def test_filter_multi_body_types_one_in_clause():
    frags, params = _build_filter_only(body_types=["სედანი", "ჯიპი"])
    body = [f for f in frags if "body_type IN" in f]
    assert len(body) == 1
    assert "სედანი" in params and "ჯიპი" in params


def test_filter_singular_and_plural_merge():
    # Legacy single value + new multi-select list collapse into one IN
    frags, params = _build_filter_only(body_type="სედანი", body_types=["ჯიპი"])
    assert len([f for f in frags if "body_type IN" in f]) == 1
    assert "სედანი" in params and "ჯიპი" in params


def test_filter_manufacturers_case_insensitive():
    frags, params = _build_filter_only(manufacturers=["BMW", "Toyota"])
    assert any("lower(manufacturer) IN" in f for f in frags)
    assert "bmw" in params and "toyota" in params


def test_filter_models_ilike():
    frags, params = _build_filter_only(models=["320", "Camry"])
    assert any("model ILIKE" in f for f in frags)
    assert "%320%" in params and "%Camry%" in params


def test_filter_locations_exact():
    frags, params = _build_filter_only(locations=["თბილისი", "ბათუმი"])
    assert any("location IN" in f for f in frags)
    assert "თბილისი" in params and "ბათუმი" in params


def test_multi_select_counts_as_a_filter_for_browse():
    from src.api.search import _has_any_filter

    assert _has_any_filter(SearchRequest(manufacturers=["BMW"]))
    assert _has_any_filter(SearchRequest(locations=["თბილისი"]))
    assert _has_any_filter(SearchRequest(fuels=["ბენზინი"]))
    assert not _has_any_filter(SearchRequest())


def test_browse_by_manufacturer_only_routes_to_browse():
    # No text, just a brand multi-select -> browse query, no 400
    sql, params, qtype = _build_query(SearchRequest(manufacturers=["BMW"]))
    assert qtype == "browse"
    assert "lower(manufacturer) IN" in sql


def test_fx_rates_single_source_of_truth():
    # The SQL price-conversion CASE and the Python _clean_price helper must use the same FX rates - both derive from config
    # FX_RATES_TO_USD, never drift
    from src.common.config import FX_RATES_TO_USD
    from src.api.search import _PRICE_USD_RAW, _FX_TO_USD

    assert _FX_TO_USD is FX_RATES_TO_USD
    for cur, rate in FX_RATES_TO_USD.items():
        assert f"WHEN '{cur}' THEN price_amount::float * {rate}" in _PRICE_USD_RAW


def test_search_hides_gone_listings_but_vin_and_phone_do_not():
    # browse and text search only show live rows
    sql, _, _ = _build_query(SearchRequest(query="camry"))
    assert "gone_at IS NULL" in sql
    sql, _, _ = _build_query(SearchRequest(manufacturers=["Toyota"]))
    assert "gone_at IS NULL" in sql

    # a VIN or phone lookup is how you find a car that has already sold
    sql, _, _ = _build_query(SearchRequest(query="JT2BF22K1W0123456"))
    assert "gone_at" not in sql
    sql, _, _ = _build_query(SearchRequest(query="595515141"))
    assert "gone_at" not in sql
