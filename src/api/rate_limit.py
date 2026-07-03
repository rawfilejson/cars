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
IP X-Forwarded-For-ის ბოლო (proxy-ჩამატებულ) ჩანაწერიდან — კლიენტს
მარცხნიდან ცრუ IP-ის prepend არ შეუძლია.
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

    X-Forwarded-For-ის ბოლო (rightmost) public IP-ს ვიღებთ: ამ ჩანაწერს
    hosting proxy ამატებს კავშირის რეალური IP-ით, ხოლო კლიენტის მიერ
    მარცხნიდან prepend-ული ცრუ IP-ები იგნორდება. fallback: peer host.
    """
    fwd = request.headers.get("x-forwarded-for", "")
    for part in reversed(fwd.split(",")):
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


def check_rate_limit(request: Request, is_pagination: bool = False) -> int | None:
    """ცდის ჩატარებამდე rate-limit-ის შემოწმება. აბრუნებს დარჩენილ ცდებს.

    is_pagination=True (page>1) — cooldown-ს არ ვამოწმებთ: არსებული შედეგის
    გვერდებზე გადასვლა ახალი ძიება არ არის (IP-ის საათობრივი ჭერი მაინც მოქმედებს).

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

    # SEARCH_LIMIT_PER_HOUR <= 0 ნიშნავს „საათობრივი ლიმიტი გამორთულია" — მხოლოდ cooldown მოქმედებს
    hourly_on = SEARCH_LIMIT_PER_HOUR > 0
    if hourly_on and count_last_hour >= SEARCH_LIMIT_PER_HOUR:
        raise _limit_error(SEARCH_LIMIT_PER_HOUR)

    # IP backstop რჩება scraping-ის წინააღმდეგ (ჩვეულებრივ მომხმარებელს არ ეხება)
    if ip and SEARCH_LIMIT_PER_IP_HOUR > 0 and ip_count >= SEARCH_LIMIT_PER_IP_HOUR:
        raise _limit_error(SEARCH_LIMIT_PER_IP_HOUR)

    return (SEARCH_LIMIT_PER_HOUR - count_last_hour - 1) if hourly_on else None


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
