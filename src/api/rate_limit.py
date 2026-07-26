# rate limiting on an anonymous browser token, with the IP as a backstop
# one public IP is often shared by a whole home wifi or a mobile CGNAT, so the main
# identity is a token the browser keeps in localStorage and sends as X-Client-Id
# the IP only exists to stop someone rotating tokens
# a cooldown and an hourly limit apply per token, the hourly ceiling per IP
# timing comes from the database NOW(), we don't trust the client's clock
# the IP comes from CF-Connecting-IP, which Cloudflare overwrites so it cannot be
# forged. without Cloudflare the fallback is the last public IP in XFF

from __future__ import annotations

import ipaddress
import re

from fastapi import HTTPException, Request, status

from src.api.db_pool import connection
from src.common.config import (
    CONTACT_INSTAGRAM,
    SEARCH_COOLDOWN_SECONDS,
    SEARCH_LIMIT_PER_HOUR,
    SEARCH_LIMIT_PER_IP_HOUR,
)


_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _is_public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def client_ip(request: Request) -> str | None:
    # the real client IP, or None if we cannot work it out
    #
    # CF-Connecting-IP is trustworthy because the origin is only reachable through
    # Cloudflare's edge, so a client cannot supply or fake it. Running without
    # Cloudflare, fall back to the last public IP in XFF, then the peer host.
    cf = request.headers.get("cf-connecting-ip", "").strip()
    if _is_public_ip(cf):
        return cf

    fwd = request.headers.get("x-forwarded-for", "")
    for part in reversed(fwd.split(",")):
        ip = part.strip()
        if _is_public_ip(ip):
            return ip

    host = request.client.host if request.client else ""
    return host if _is_ip(host) else None


def client_token(request: Request) -> str | None:
    # the browser's anonymous id from X-Client-Id, checked for shape
    tok = request.headers.get("x-client-id", "").strip()
    return tok if _CLIENT_ID_RE.match(tok) else None


def _cooldown_error(sec_since_last: float) -> HTTPException:
    wait = int(SEARCH_COOLDOWN_SECONDS - sec_since_last) + 1
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"code": "cooldown", "wait": wait},
        headers={"Retry-After": str(wait)},
    )


def _limit_error(limit: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"code": "rate_limited", "limit": limit, "contact": CONTACT_INSTAGRAM},
    )


def check_rate_limit(request: Request, is_pagination: bool = False) -> int | None:
    # check the rate limit before a search. returns how many tries are left
    #
    # is_pagination=True (page > 1) skips the cooldown, because paging through
    # results you already have is not a new search. The hourly IP ceiling still applies.
    #
    # Raises:
    #     HTTPException 429 for the cooldown, the token's hourly limit, or the IP ceiling
    ip = client_ip(request)
    token = client_token(request)

    if token:
        identity_col, identity_val = "client_id", token
    elif ip:
        identity_col, identity_val = "user_ip", ip
    else:
        return None

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    EXTRACT(EPOCH FROM (NOW() - MAX(created_at))) AS sec_since_last,
                    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 hour')
                        AS count_last_hour
                FROM searches
                WHERE {identity_col} = %s
                """,
                (identity_val,),
            )
            row = cur.fetchone()

            ip_count = 0
            if ip:
                cur.execute(
                    """
                    SELECT COUNT(*) AS n FROM searches
                    WHERE user_ip = %s AND created_at > NOW() - INTERVAL '1 hour'
                    """,
                    (ip,),
                )
                ip_row = cur.fetchone()
                ip_count = int(ip_row["n"] or 0) if ip_row else 0

    sec_since_last = (
        row["sec_since_last"] if row and row["sec_since_last"] is not None else None
    )
    count_last_hour = int(row["count_last_hour"] or 0) if row else 0

    if not is_pagination and sec_since_last is not None and sec_since_last < SEARCH_COOLDOWN_SECONDS:
        raise _cooldown_error(sec_since_last)

    # SEARCH_LIMIT_PER_HOUR <= 0 turns the hourly limit off, leaving only the cooldown
    hourly_on = SEARCH_LIMIT_PER_HOUR > 0
    if hourly_on and count_last_hour >= SEARCH_LIMIT_PER_HOUR:
        raise _limit_error(SEARCH_LIMIT_PER_HOUR)

    # the IP backstop is aimed at scrapers, not at ordinary visitors
    if ip and SEARCH_LIMIT_PER_IP_HOUR > 0 and ip_count >= SEARCH_LIMIT_PER_IP_HOUR:
        raise _limit_error(SEARCH_LIMIT_PER_IP_HOUR)

    return (SEARCH_LIMIT_PER_HOUR - count_last_hour - 1) if hourly_on else None


def log_search(
    request: Request,
    query: str,
    query_type: str,
    results_count: int,
) -> None:
    # record the search in the database
    ip = client_ip(request)
    token = client_token(request)
    user_agent = request.headers.get("user-agent", "")[:500]

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO searches
                  (query, query_type, results_count, user_ip, user_agent, client_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (query[:500], query_type, results_count, ip, user_agent, token),
            )
        conn.commit()
