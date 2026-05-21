"""
ძიების endpoints — VIN, ნომერი, თავისუფალი ტექსტი.

სრულიად უფასო, ანონიმური — მხოლოდ IP-ით ლიმიტი.
"""

from __future__ import annotations

import re

import psycopg
from fastapi import APIRouter, Request, status, HTTPException
from psycopg.rows import dict_row

from src.api.rate_limit import check_rate_limit, log_search
from src.api.schemas import CarPublic, SearchRequest, SearchResponse
from src.common.config import DATABASE_URL, R2_PUBLIC_URL


router = APIRouter(prefix="/search", tags=["search"])


def _normalize_phone_query(raw: str) -> str:
    """ნომრის გასუფთავება — მხოლოდ ციფრები, ბოლო 9 (ქართული მობილური).

    შენიშვნა: ბაზაში ნომრები ყოველთვის +-ით იწყება (მაგ: +995555555555).
    მომხმარებელმა შეიძლება ჩაწეროს:
      "555555555"         → suffix "555555555" → მოძებნავს `LIKE '%555555555'`
      "+995555555555"     → digits "995555555555" → suffix "555555555"
      "995 555 555 555"   → იგივე
      "555-55-55-55"      → digits "5555555555" → suffix "555555555" (10 ციფრის შემთხვევაში ბოლო 9)
    ყველა ვარიანტი ერთსა და იმავე ნომერს მოძებნავს.
    """
    digits = re.sub(r"\D", "", raw)
    return digits[-9:] if len(digits) > 9 else digits


def _build_query(req: SearchRequest) -> tuple[str, tuple, str]:
    """SQL + params + query_type — VIN > Phone > Free text პრიორიტეტი."""
    if req.vin and len(req.vin) == 17:
        return (
            "SELECT * FROM cars WHERE vin = %s ORDER BY updated_at DESC LIMIT 50",
            (req.vin.upper(),),
            "vin",
        )
    if req.vin:
        return (
            "SELECT * FROM cars WHERE vin LIKE %s ORDER BY updated_at DESC LIMIT 50",
            (req.vin.upper() + "%",),
            "vin",
        )
    if req.phone:
        # ნომრის გასუფთავება — მომხმარებლისგან მოსული ფორმატი არ აქვს მნიშვნელობა
        suffix = _normalize_phone_query(req.phone)
        if len(suffix) < 4:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ნომერი მინიმუმ 4 ციფრი უნდა იყოს",
            )
        return (
            "SELECT * FROM cars WHERE phone LIKE %s ORDER BY updated_at DESC LIMIT 50",
            ("%" + suffix,),                            # match by trailing digits
            "phone",
        )
    if req.free_text:
        text = req.free_text.strip()
        # Reject obvious one-word brand searches like "Toyota" — they'd return
        # thousands of rows and serve nobody. Frontend has the same guard.
        words = [w for w in text.split() if w]
        has_digit = any(c.isdigit() for c in text)
        too_generic = (
            len(text) < 5
            or (len(words) == 1 and not has_digit and len(text) < 8)
        )
        if too_generic:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Search too broad — add year, city, or model trim "
                       "(e.g. \"Toyota Camry 2020 თბილისი\").",
            )
        return (
            """
            SELECT *, similarity(description, %s) AS score FROM cars
            WHERE description %% %s
            ORDER BY score DESC, updated_at DESC LIMIT 30
            """,
            (text, text),
            "free_text",
        )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="მინიმუმ ერთი ფილდი უნდა შეავსოთ (vin / phone / free_text)",
    )


def _row_to_public(row: dict) -> CarPublic:
    """DB row → CarPublic. ფოტოები R2 public URL-ად."""
    image_keys = row.get("image_keys") or []
    image_urls_public = [
        f"{R2_PUBLIC_URL.rstrip('/')}/{key}" if R2_PUBLIC_URL else key
        for key in image_keys
    ] or (row.get("image_urls") or [])

    return CarPublic(
        id=row["id"],
        source=row["source"],
        source_id=row["source_id"],
        url=row["url"],
        manufacturer=row.get("manufacturer") or "",
        model=row.get("model") or "",
        year=row.get("year"),
        body_type=row.get("body_type") or "",
        price_amount=row.get("price_amount"),
        price_currency=row.get("price_currency") or "",
        price_with_customs=row.get("price_with_customs"),
        engine_volume_l=(
            float(row["engine_volume_l"])
            if row.get("engine_volume_l") is not None else None
        ),
        engine_type=row.get("engine_type") or "",
        power_hp=row.get("power_hp"),
        gearbox=row.get("gearbox") or "",
        drive_wheels=row.get("drive_wheels") or "",
        mileage_km=row.get("mileage_km"),
        color=row.get("color") or "",
        steering=row.get("steering") or "",
        customs_cleared=row.get("customs_cleared"),
        vin=row.get("vin") or "",
        location=row.get("location") or "",
        seller_name=row.get("seller_name") or "",
        phone=row.get("phone") or "",
        description=row.get("description") or "",
        video_url=row.get("video_url") or "",
        image_urls=image_urls_public,
        image_keys=image_keys,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.post("", response_model=SearchResponse)
def search(req: SearchRequest, request: Request) -> SearchResponse:
    """ძიება — VIN, ნომერი, ან თავისუფალი ტექსტი. სრულიად უფასო."""

    # IP-ით rate limit
    remaining = check_rate_limit(request)

    sql, params, query_type = _build_query(req)

    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    results = [_row_to_public(row) for row in rows]
    results_count = len(results)

    # log
    query_repr = req.vin or req.phone or req.free_text or ""
    log_search(request, query_repr, query_type, results_count)

    return SearchResponse(
        query_type=query_type,
        results=results,
        results_count=results_count,
        charged=False,
        remaining_free_searches=remaining,
    )
