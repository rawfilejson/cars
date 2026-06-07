"""
Rate limiting — ბრაუზერის ანონიმური token-ი (მთავარი) + IP (backstop).

ანონიმური საიტი, ავტორიზაცია არ გვაქვს. ერთ public IP-ს ხშირად ბევრი კაცი
იზიარებს (სახლის WiFi, ოპერატორის CGNAT), ამიტომ მთავარ იდენტობად ბრაუზერის
token-ს ვიღებთ (X-Client-Id, localStorage-დან): ერთ ქსელში ორი ადამიანი
ერთმანეთს ლიმიტს აღარ უჭამს. IP მხოლოდ abuse-ის ჭერია (token-ის როტაცია).

  * Cooldown: ცდებს შორის მინ. N წამი — token-ზე
  * საათობრივი ლიმიტი: token-ზე
  * საათობრივი ჭერი: IP-ზე (backstop)

დრო DB-ის NOW()-ით იზომება — კლიენტის საათს არ ვენდობით.
onrender.com Cloudflare-ის უკანაა, ამიტომ რეალური IP CF-Connecting-IP-შია.
"""

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
    """რეალური კლიენტის IP, ან None თუ ვერ დავადგინეთ.

    Cloudflare-ი CF-Connecting-IP-ს ყოველთვის გადააწერს კავშირის რეალური
    IP-ით — კლიენტი ვერ აყალბებს. fallback: X-Forwarded-For-ის პირველი
    public IP (CF-ის გარეშე dev), შემდეგ peer host.
    """
    cf = request.headers.get("cf-connecting-ip", "").strip()
    if _is_ip(cf):
        return cf

    fwd = request.headers.get("x-forwarded-for", "")
    for part in fwd.split(","):
        ip = part.strip()
        if _is_public_ip(ip):
            return ip

    host = request.client.host if request.client else ""
    return host if _is_ip(host) else None


def client_token(request: Request) -> str | None:
    """ბრაუზერის ანონიმური id (X-Client-Id header). ფორმატით ვამოწმებთ."""
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


def check_rate_limit(request: Request) -> int:
    """ცდის ჩატარებამდე rate-limit-ის შემოწმება. აბრუნებს დარჩენილ ცდებს.

    Raises:
        HTTPException 429 — cooldown, token-ის საათობრივი, ან IP-ის ჭერი.
    """
    ip = client_ip(request)
    token = client_token(request)

    if token:
        identity_col, identity_val = "client_id", token
    elif ip:
        identity_col, identity_val = "user_ip", ip
    else:
        return SEARCH_LIMIT_PER_HOUR

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

    if sec_since_last is not None and sec_since_last < SEARCH_COOLDOWN_SECONDS:
        raise _cooldown_error(sec_since_last)

    if count_last_hour >= SEARCH_LIMIT_PER_HOUR:
        raise _limit_error(SEARCH_LIMIT_PER_HOUR)

    if ip and ip_count >= SEARCH_LIMIT_PER_IP_HOUR:
        raise _limit_error(SEARCH_LIMIT_PER_IP_HOUR)

    return SEARCH_LIMIT_PER_HOUR - count_last_hour - 1


def log_search(
    request: Request,
    query: str,
    query_type: str,
    results_count: int,
) -> None:
    """საძიებო event-ის DB-ში ჩაწერა."""
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
