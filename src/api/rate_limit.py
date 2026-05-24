"""
Rate limiting — მხოლოდ IP-ის მიხედვით.

ანონიმური საიტი — არანაირი ავტორიზაცია. დაცვა:
  * **Cooldown:** ცდებს შორის მინიმუმ N წამი (default: 10)
  * **საათობრივი ლიმიტი:** IP-ზე 30 ცდა საათში (default)
  * **Cloudflare WAF** — გარეთ, application-ის გარეთ

ლიმიტი გადასცილების შემთხვევაში — Instagram კონტაქტი (@deme.brn).

შენიშვნა: დროის გაანგარიშება ხდება მთლიანად DB-ის NOW()-ით,
რომ კლიენტისა და DB სერვერის სათები არ აერიოს.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from src.api.db_pool import connection
from src.common.config import (
    CONTACT_INSTAGRAM,
    SEARCH_COOLDOWN_SECONDS,
    SEARCH_LIMIT_PER_HOUR,
)


def client_ip(request: Request) -> str:
    """Real IP-ის ამოღება — Cloudflare proxy-ის შემდეგ ან პირდაპირ."""
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request) -> int:
    """ცდის ჩატარებამდე rate-limit-ის შემოწმება.

    აბრუნებს დარჩენილი ცდების რაოდენობას ამ საათში (ცდის შემდეგ).

    Raises:
        HTTPException 429 — cooldown ან საათობრივი ლიმიტი.
    """
    ip = client_ip(request)

    with connection() as conn:
        with conn.cursor() as cur:
            # ერთ query-ში ვიღებთ ორივეს:
            #   ბოლო ცდიდან რამდენი წამი გავიდა (DB-ის NOW()-ით)
            #   ბოლო 1 საათში რამდენი ცდა იყო
            cur.execute(
                """
                SELECT
                    EXTRACT(EPOCH FROM (NOW() - MAX(created_at))) AS sec_since_last,
                    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 hour')
                        AS count_last_hour
                FROM searches
                WHERE user_ip = %s
                """,
                (ip,),
            )
            row = cur.fetchone()

    # row_factory=dict_row in the pool — extract by column name
    sec_since_last = row["sec_since_last"] if row and row["sec_since_last"] is not None else None
    count_last_hour = int(row["count_last_hour"] or 0) if row else 0

    # Cooldown
    if sec_since_last is not None and sec_since_last < SEARCH_COOLDOWN_SECONDS:
        wait = int(SEARCH_COOLDOWN_SECONDS - sec_since_last) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"მოიცადე {wait} წამი შემდეგი ცდისთვის",
            headers={"Retry-After": str(wait)},
        )

    # საათობრივი ლიმიტი
    if count_last_hour >= SEARCH_LIMIT_PER_HOUR:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"საათობრივი ლიმიტი ({SEARCH_LIMIT_PER_HOUR} ცდა) ამოწურეთ. "
                f"შემდეგ საათში სცადეთ ან მომწერეთ Instagram-ზე {CONTACT_INSTAGRAM} "
                f"მეტი ლიმიტის მისაღებად."
            ),
        )

    return SEARCH_LIMIT_PER_HOUR - count_last_hour - 1


def log_search(
    request: Request,
    query: str,
    query_type: str,
    results_count: int,
) -> None:
    """საძიებო event-ის DB-ში ჩაწერა."""
    ip = client_ip(request)
    user_agent = request.headers.get("user-agent", "")[:500]

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO searches
                  (query, query_type, results_count, paid, user_ip, user_agent)
                VALUES (%s, %s, %s, FALSE, %s, %s)
                """,
                (query[:500], query_type, results_count, ip, user_agent),
            )
        conn.commit()
