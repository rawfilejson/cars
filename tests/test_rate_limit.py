"""client identity resolution — XFF rightmost-public scan, token format.

These helpers don't touch the DB, so a fake request (headers + client) is enough.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.datastructures import Headers

from src.api.rate_limit import client_ip, client_token


def _req(headers: dict | None = None, client_host: str | None = None):
    # real Starlette Request.headers is case-insensitive — model that faithfully
    # so the mock can't pass for the wrong reason.
    client = SimpleNamespace(host=client_host) if client_host is not None else None
    return SimpleNamespace(headers=Headers(headers or {}), client=client)


def test_cf_connecting_ip_not_trusted():
    """API isn't behind Cloudflare — a client-set cf-connecting-ip must be ignored."""
    req = _req(
        {"cf-connecting-ip": "8.8.8.8", "x-forwarded-for": "1.1.1.1"},
        client_host="9.9.9.9",
    )
    assert client_ip(req) == "1.1.1.1"   # rightmost public XFF, not the spoofable header


def test_xff_prepended_spoof_is_ignored():
    """Client prepends a fake IP; the proxy appends the real one — we take the real (rightmost)."""
    req = _req({"x-forwarded-for": "6.6.6.6, 8.8.4.4"})
    assert client_ip(req) == "8.8.4.4"


def test_xff_skips_trailing_private_takes_rightmost_public():
    req = _req({"x-forwarded-for": "10.0.0.1, 8.8.4.4, 192.168.1.2"})
    assert client_ip(req) == "8.8.4.4"


def test_xff_all_private_falls_back_to_peer_host():
    req = _req({"x-forwarded-for": "10.0.0.1, 192.168.0.1"}, client_host="1.2.3.4")
    assert client_ip(req) == "1.2.3.4"


def test_no_xff_falls_back_to_host():
    assert client_ip(_req({}, client_host="1.2.3.4")) == "1.2.3.4"


def test_no_identifiable_ip_returns_none():
    assert client_ip(_req()) is None
    assert client_ip(_req({"x-forwarded-for": "garbage"}, client_host="also-garbage")) is None


@pytest.mark.parametrize("token,expected", [
    ("a1b2c3d4e5", "a1b2c3d4e5"),
    ("123e4567-e89b-12d3-a456-426614174000", "123e4567-e89b-12d3-a456-426614174000"),
    ("  pad_ded-token  ", "pad_ded-token"),   # trimmed before validation
    ("short", None),                           # < 8 chars
    ("' OR 1=1", None),                         # bad chars
    ("", None),
])
def test_client_token(token, expected):
    assert client_token(_req({"x-client-id": token})) == expected


def test_client_token_missing_header():
    assert client_token(_req()) is None


def test_client_token_case_insensitive_header():
    """Starlette headers are case-insensitive — an uppercase name still resolves."""
    assert client_token(_req({"X-Client-Id": "a1b2c3d4e5"})) == "a1b2c3d4e5"
