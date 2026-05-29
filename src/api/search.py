"""
ძიების endpoint — ერთიანი smart search + legacy ცალკეული ფილდები.

ახალი ფრონტი: `query` ერთად, backend ცნობს რა ტიპისაა (VIN/phone/ტექსტი).
ძველი ფრონტი (Carba): vin/phone/free_text ცალკე ფილდები. deprecated.

სრულიად უფასო, ანონიმური — მხოლოდ IP-ით ლიმიტი.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Request, status, HTTPException

from src.api.db_pool import connection
from src.api.rate_limit import check_rate_limit, log_search
from src.api.schemas import CarPublic, SearchRequest, SearchResponse
from src.common.config import R2_PUBLIC_URL


router = APIRouter(prefix="/search", tags=["search"])

# detail-page endpoint lives at /car/{key} — separate router so it's not nested under /search
car_router = APIRouter(prefix="/car", tags=["car"])

PAGE_SIZE = 25

# {source}-{source_id} permalink key. Both sources use numeric IDs.
_CAR_KEY_RE = re.compile(r"^(autopapa|myauto)-(\d+)$")


# WHERE clause haystack — `search_blob` is a STORED generated column that
# concatenates and lowercases all searchable fields. It has a gin_trgm
# index, so ILIKE '%word%' against it is fast (was a full seq scan over
# 150k rows before).
_SEARCH_BLOB = "search_blob"

# Ranking haystack — short, identity-relevant fields only. Without this
# narrow blob, similarity over the long description text dominates and a
# search for "Toyota Camry" can rank a Land Cruiser above an actual Camry.
_TITLE_BLOB = (
    "COALESCE(manufacturer,'') || ' ' || "
    "COALESCE(model,'') || ' ' || "
    "COALESCE(CAST(year AS TEXT),'') || ' ' || "
    "COALESCE(location,'')"
)


_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

# rough USD-equivalent for sorting across currencies
_PRICE_IN_USD = (
    "(CASE price_currency "
    "WHEN 'USD' THEN price_amount::float "
    "WHEN 'EUR' THEN price_amount::float * 1.08 "
    "WHEN 'GEL' THEN price_amount::float * 0.37 "
    "END)"
)

_SORT_CLAUSES = {
    "newest":       "updated_at DESC",
    "price_asc":    f"{_PRICE_IN_USD} ASC NULLS LAST, updated_at DESC",
    "price_desc":   f"{_PRICE_IN_USD} DESC NULLS LAST, updated_at DESC",
    "year_desc":    "year DESC NULLS LAST, updated_at DESC",
    "year_asc":     "year ASC NULLS LAST, updated_at DESC",
    "mileage_asc":  "mileage_km ASC NULLS LAST, updated_at DESC",
    "mileage_desc": "mileage_km DESC NULLS LAST, updated_at DESC",
}


def _normalize_phone_query(raw: str) -> str:
    """ნომრის გასუფთავება — მხოლოდ ციფრები, ბოლო 9 (ქართული მობილური)."""
    digits = re.sub(r"\D", "", raw)
    return digits[-9:] if len(digits) > 9 else digits


def _filter_clauses(req: SearchRequest) -> tuple[list[str], list]:
    """Filter SQL fragments + their parameter values."""
    fragments: list[str] = []
    params: list = []
    if req.year_from is not None:
        fragments.append("year >= %s")
        params.append(req.year_from)
    if req.year_to is not None:
        fragments.append("year <= %s")
        params.append(req.year_to)
    if req.price_from is not None:
        fragments.append(f"{_PRICE_IN_USD} >= %s")
        params.append(req.price_from)
    if req.price_to is not None:
        fragments.append(f"{_PRICE_IN_USD} <= %s")
        params.append(req.price_to)
    if req.mileage_from is not None:
        fragments.append("mileage_km >= %s")
        params.append(req.mileage_from)
    if req.mileage_to is not None:
        fragments.append("mileage_km <= %s")
        params.append(req.mileage_to)
    return fragments, params


def _sort_clause(sort: str | None) -> str:
    """ORDER BY tail string. Default = newest."""
    return _SORT_CLAUSES.get(sort or "newest", _SORT_CLAUSES["newest"])


def _has_any_filter(req: SearchRequest) -> bool:
    return any(
        getattr(req, k) is not None
        for k in ("year_from", "year_to", "price_from", "price_to", "mileage_from", "mileage_to")
    )


_PHONE_CHARS_RE = re.compile(r"[\d\s+()\-.]+")


def _looks_like_phone(text: str) -> bool:
    """7+ ციფრი + ფონის სიმბოლოები (digits, spaces, +, -, parens, dots)."""
    digits = re.sub(r"\D", "", text)
    if len(digits) < 7:
        return False
    # All chars are phone-shaped → definitely a phone
    if _PHONE_CHARS_RE.fullmatch(text):
        return True
    # Mixed junk but mostly digits → probably a phone
    return len(digits) / len(text) > 0.5


def _paginate(sql_core: str, params: tuple, page: int) -> tuple[str, tuple]:
    """Wrap a SELECT with COUNT(*) OVER () + LIMIT/OFFSET pagination."""
    # `sql_core` must already contain ORDER BY. We splice COUNT(*) into the
    # SELECT list and append LIMIT/OFFSET.
    offset = (page - 1) * PAGE_SIZE
    sql_paginated = sql_core + f" LIMIT {PAGE_SIZE} OFFSET {offset}"
    # Caller can wrap the SELECT however it likes — we just append paging.
    return sql_paginated, params


def _smart_route(req: SearchRequest, text: str) -> tuple[str, tuple, str]:
    """Auto-detect VIN / phone / freeform text. Filters + sort apply to
    freeform/browse (VIN/phone are exact lookups — filters don't make sense)."""
    text = text.strip()
    if not text:
        return _browse_query(req)

    upper = text.upper()
    if _VIN_RE.match(upper):
        sql = "SELECT *, COUNT(*) OVER () AS _total FROM cars WHERE vin = %s ORDER BY updated_at DESC"
        return _paginate(sql, (upper,), req.page) + ("vin",)

    if _looks_like_phone(text):
        suffix = _normalize_phone_query(text)
        sql = (
            "SELECT *, COUNT(*) OVER () AS _total FROM cars "
            "WHERE regexp_replace(phone, '\\D', '', 'g') LIKE %s "
            "ORDER BY updated_at DESC"
        )
        return _paginate(sql, ("%" + suffix,), req.page) + ("phone",)

    # Freeform — Ctrl-F across all fields, similarity for ranking, plus filters
    words = [w for w in text.split() if w]
    if not words or len(text) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "query_too_vague"},
        )

    # search_blob is lowercased — use LIKE (case-sensitive) on lowered
    # patterns to let Postgres use the gin_trgm index efficiently.
    word_clauses = " AND ".join([f"{_SEARCH_BLOB} LIKE %s"] * len(words))
    patterns = [f"%{w.lower()}%" for w in words]

    filter_frags, filter_params = _filter_clauses(req)
    extra_where = (" AND " + " AND ".join(filter_frags)) if filter_frags else ""

    if req.sort:
        order_by = _sort_clause(req.sort)
        sql = f"""
            SELECT *, COUNT(*) OVER () AS _total
            FROM cars
            WHERE {word_clauses}{extra_where}
            ORDER BY {order_by}
        """
        params = (*patterns, *filter_params)
    else:
        # Score on TITLE_BLOB (manufacturer+model+year+location) — short
        # identity-fields-only. This prevents long descriptions from drowning
        # the actual title relevance ("Toyota Camry" → real Camrys first).
        sql = f"""
            SELECT *, COUNT(*) OVER () AS _total,
                similarity({_TITLE_BLOB}, %s) AS score
            FROM cars
            WHERE {word_clauses}{extra_where}
            ORDER BY score DESC NULLS LAST, updated_at DESC
        """
        params = (text, *patterns, *filter_params)

    return _paginate(sql, tuple(params), req.page) + ("search",)


def _browse_query(req: SearchRequest) -> tuple[str, tuple, str]:
    """No text — just filters + sort. e.g. all 2018-2022 cars under $20k."""
    if not _has_any_filter(req):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "query_empty"},
        )
    filter_frags, filter_params = _filter_clauses(req)
    where = " AND ".join(filter_frags)
    order_by = _sort_clause(req.sort)
    sql = f"""
        SELECT *, COUNT(*) OVER () AS _total
        FROM cars
        WHERE {where}
        ORDER BY {order_by}
    """
    return _paginate(sql, tuple(filter_params), req.page) + ("browse",)


def _build_query(req: SearchRequest) -> tuple[str, tuple, str]:
    """Routes to smart-search if `query` set, otherwise legacy logic, otherwise browse."""
    if req.query:
        return _smart_route(req, req.query)

    # ----- Legacy path (kept for old Carba frontend) -----
    if req.vin and len(req.vin) == 17:
        sql = "SELECT *, COUNT(*) OVER () AS _total FROM cars WHERE vin = %s ORDER BY updated_at DESC"
        return _paginate(sql, (req.vin.upper(),), req.page) + ("vin",)
    if req.vin:
        sql = "SELECT *, COUNT(*) OVER () AS _total FROM cars WHERE vin LIKE %s ORDER BY updated_at DESC"
        return _paginate(sql, (req.vin.upper() + "%",), req.page) + ("vin",)
    if req.phone:
        suffix = _normalize_phone_query(req.phone)
        if len(suffix) < 4:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "phone_too_short"},
            )
        sql = (
            "SELECT *, COUNT(*) OVER () AS _total FROM cars "
            "WHERE regexp_replace(phone, '\\D', '', 'g') LIKE %s "
            "ORDER BY updated_at DESC"
        )
        return _paginate(sql, ("%" + suffix,), req.page) + ("phone",)
    if req.free_text:
        return _smart_route(req, req.free_text)

    if _has_any_filter(req):
        return _browse_query(req)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "query_empty"},
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

    # IP-ით rate limit — every page request counts as a separate search
    remaining = check_rate_limit(request)

    sql, params, query_type = _build_query(req)

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    # _total comes from COUNT(*) OVER () in the SQL; same value on every row.
    total_count = int(rows[0]["_total"]) if rows else 0

    results = [_row_to_public(row) for row in rows]
    results_count = len(results)

    query_repr = req.query or req.vin or req.phone or req.free_text or ""
    log_search(request, query_repr, query_type, results_count)

    return SearchResponse(
        query_type=query_type,
        results=results,
        results_count=results_count,
        total_count=total_count,
        page=req.page,
        page_size=PAGE_SIZE,
        remaining_searches=remaining,
    )


@car_router.get("/{key}", response_model=CarPublic)
def get_car(key: str) -> CarPublic:
    """ერთი მანქანის ფეთჩი permalink-ისთვის. {key} = {source}-{source_id},
    მაგ. /car/myauto-121951594. Rate limit-ი არ ვცემთ — ეს არ არის ძიება."""
    m = _CAR_KEY_RE.match(key)
    if not m:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "car_invalid_key"},
        )
    source, source_id = m.group(1), m.group(2)

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM cars WHERE source = %s AND source_id = %s",
                (source, source_id),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "car_not_found"},
        )
    return _row_to_public(row)
