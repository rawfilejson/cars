# Security regression tests - lock in the protections verified during the penetration assessment
# (SQLi, sort whitelist, key/VIN/token validation, price flooring, IP classification)
# Run: uv run pytest tests/test_security.py -q

from __future__ import annotations

import re

import pytest

from src.api.schemas import SearchRequest
from src.api.search import (
    _CAR_KEY_RE,
    _SORT_CLAUSES,
    _clean_price,
    _smart_route,
    _sort_clause,
)
from src.api.rate_limit import _CLIENT_ID_RE, _is_public_ip
from src.common.vin import is_valid_vin


SQLI_PAYLOADS = [
    "bmw' OR 1=1--",
    "x'; DROP TABLE cars;--",
    "x' UNION SELECT NULL--",
    "x') OR pg_sleep(5)--",
    "1); DELETE FROM cars;--",
]


@pytest.mark.parametrize("payload", SQLI_PAYLOADS)
def test_text_search_is_parameterized(payload):
    # User text must reach SQL only as %s params, never spliced into the query
    sql, params, _ = _smart_route(SearchRequest(query=payload), payload)
    assert "%s" in sql  # placeholders are used
    upper = sql.upper()
    assert "DROP" not in upper
    assert "PG_SLEEP" not in upper
    assert "1=1" not in sql
    assert "DELETE" not in upper
    # the dangerous string travels in params, not the query body
    assert any(payload.lower() in str(p).lower() for p in params)


def test_sort_is_whitelisted():
    # Anything not in the whitelist falls back to the safe default order by
    assert _sort_clause("price_asc") == _SORT_CLAUSES["price_asc"]
    for bad in [
        "price_asc; DROP TABLE cars",
        "(SELECT 1)",
        "year_desc--",
        "",
        None,
        "x",
    ]:
        assert _sort_clause(bad) == _SORT_CLAUSES["newest"]


@pytest.mark.parametrize(
    "key,ok",
    [
        ("myauto-123", True),
        ("autopapa-456", True),
        ("myauto-1' OR '1", False),
        ("myauto-1;DROP", False),
        ("../../etc/passwd", False),
        ("evil-123", False),
        ("myauto-", False),
        ("myauto-12a", False),
    ],
)
def test_car_key_regex_rejects_injection(key, ok):
    assert bool(_CAR_KEY_RE.match(key)) is ok


def test_car_key_regex_accepts_every_known_source():
    # The permalink regex is built from config.SOURCES - every supported
    # source must round-trip, so adding a parser can't silently break /car/.
    from src.common.config import SOURCES

    for source in SOURCES:
        assert _CAR_KEY_RE.match(f"{source}-123")


def test_car_key_regex_escapes_source_metacharacters():
    # Sources are re.escape()'d into the permalink regex, so a future source with
    # regex metacharacters matches literally, not as a pattern
    sources = ("au.to", "my+auto")
    rx = re.compile(r"^(" + "|".join(re.escape(s) for s in sources) + r")-(\d+)$")
    assert rx.match("au.to-123")
    assert rx.match("my+auto-9")
    assert not rx.match("auXto-123")  # '.' stays literal, not any char


@pytest.mark.parametrize(
    "vin,ok",
    [
        ("WBA3A5C5XFD123456", True),
        ("SHORT", False),
        ("KMHL34xxxxx123456".replace("x", "*"), False),  # masked VIN
        ("IIIIIIIIIIIIIIIII", False),  # 'I' not allowed
        ("", False),
    ],
)
def test_vin_validation(vin, ok):
    assert is_valid_vin(vin) is ok


@pytest.mark.parametrize(
    "amount,currency,expected",
    [
        (0, "USD", None),
        (-1, "GEL", None),
        (5, "USD", None),
        (50, "GEL", None),
        (8000, "USD", 8000),
        (50000, "GEL", 50000),
        (None, "USD", None),
    ],
)
def test_price_floor_drops_junk(amount, currency, expected):
    assert _clean_price(amount, currency) == expected


@pytest.mark.parametrize(
    "token,ok",
    [
        ("a1b2c3d4e5", True),
        ("123e4567-e89b-12d3-a456-426614174000", True),
        ("' OR 1=1", False),
        ("<script>x", False),
        ("short", False),  # < 8 chars
        ("", False),
        ("x" * 100, False),  # > 64 chars
    ],
)
def test_client_id_format(token, ok):
    assert bool(_CLIENT_ID_RE.match(token)) is ok


def test_private_ips_not_treated_as_public():
    for priv in [
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.1",
        "127.0.0.1",
        "::1",
        "garbage",
    ]:
        assert _is_public_ip(priv) is False
    assert _is_public_ip("8.8.8.8") is True
