"""
ძიების endpoint — ერთიანი smart search + legacy ცალკეული ფილდები.

ახალი ფრონტი: `query` ერთად, backend ცნობს რა ტიპისაა (VIN/phone/ტექსტი).
ძველი ფრონტი (Carba): vin/phone/free_text ცალკე ფილდები. deprecated.

სრულიად უფასო, ანონიმური — მხოლოდ IP-ით ლიმიტი.
"""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict

from fastapi import APIRouter, BackgroundTasks, Request, Response, status, HTTPException

from src.api.db_pool import connection
from src.api.facets import facet_variants
from src.api.rate_limit import check_rate_limit, log_search
from src.api.schemas import CarPublic, SearchCount, SearchRequest, SearchResponse
from src.common.config import FX_RATES_TO_USD, R2_PUBLIC_URL, SOURCES


router = APIRouter(prefix="/search", tags=["search"])

car_router = APIRouter(prefix="/car", tags=["car"])

PAGE_SIZE = 25

# წყაროების ენუმერაცია config.SOURCES-დან — ახალი parser ავტომატურად მუშაობს
# permalink-ში. re.escape — დაცვა მომავალი metachar-იანი სახელისგან.
_CAR_KEY_RE = re.compile(r"^(" + "|".join(re.escape(s) for s in SOURCES) + r")-(\d+)$")


_SEARCH_BLOB = "search_blob"

_TITLE_BLOB = (
    "COALESCE(manufacturer,'') || ' ' || "
    "COALESCE(model,'') || ' ' || "
    "COALESCE(CAST(year AS TEXT),'') || ' ' || "
    "COALESCE(location,'')"
)


_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

# არასწორ ფასებს (0, უარყოფითი — myauto-ს "შეთანხმებით" sentinel) NULL-ად ვთვლით,
# რომ price-sort/filter-ში არ მოხვდნენ (NULLS LAST). ~42k ასეთი ჩანაწერია ბაზაში.
_MIN_PRICE_USD = 100


# ვალუტა→USD კონვერსიის SQL CASE — config.FX_RATES_TO_USD-დან აიგება, რომ SQL-ისა
# და Python-ის (_clean_price) კურსები ვერასდროს აიცდინონ ერთმანეთს. მნიშვნელობები
# სანდო კონსტანტებია (არა user input), ამიტომ f-string-ით ჩაკერვა უსაფრთხოა.
def _build_price_usd_sql() -> str:
    whens = " ".join(
        f"WHEN '{cur}' THEN price_amount::float * {rate}"
        for cur, rate in FX_RATES_TO_USD.items()
    )
    return f"(CASE price_currency {whens} END)"


_PRICE_USD_RAW = _build_price_usd_sql()
# junk/sentinel ფასი ($100 ეკვ.-ზე ნაკლები) → NULL, რომ price-sort/filter არ აირიოს
_PRICE_IN_USD = (
    f"(CASE WHEN price_amount > 0 AND {_PRICE_USD_RAW} >= {_MIN_PRICE_USD} "
    f"THEN {_PRICE_USD_RAW} END)"
)
_FX_TO_USD = FX_RATES_TO_USD


def _clean_price(amount: int | None, currency: str | None) -> int | None:
    """junk/sentinel ფასი ($100 ეკვ.-ზე ნაკლები) → None (sort-ის იგივე ლოგიკა)."""
    if not amount or amount <= 0:
        return None
    usd = _FX_TO_USD.get(currency or "", 1.0) * amount
    return amount if usd >= _MIN_PRICE_USD else None

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


def _multi_values(singular: str | None, plural: list[str] | None) -> list[str]:
    """Merge a legacy single value + the new multi-select list — de-duped, non-empty."""
    out: list[str] = []
    if singular:
        out.append(singular)
    if plural:
        out.extend(plural)
    return list(dict.fromkeys(v for v in out if v))


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

    # facet filters — legacy single value + new multi-select list, each value
    # expanded to its canonical variants, all unioned into one IN per column.
    for singular, plural, col in (
        (req.body_type, req.body_types, "body_type"),
        (req.fuel_type, req.fuels, "engine_type"),
        (req.gearbox, req.gearboxes, "gearbox"),
        (req.drive_wheels, req.drives, "drive_wheels"),
    ):
        selected = _multi_values(singular, plural)
        if selected:
            variants: list[str] = []
            for value in selected:
                variants.extend(facet_variants(value))
            variants = list(dict.fromkeys(variants))
            placeholders = ", ".join(["%s"] * len(variants))
            fragments.append(f"{col} IN ({placeholders})")
            params.extend(variants)

    # manufacturers — exact, case-insensitive multi-select
    manufacturers = _multi_values(None, req.manufacturers)
    if manufacturers:
        placeholders = ", ".join(["%s"] * len(manufacturers))
        fragments.append(f"lower(manufacturer) IN ({placeholders})")
        params.extend(m.lower() for m in manufacturers)

    # models — substring match (base-model names live inside the full trim string)
    models = _multi_values(None, req.models)
    if models:
        ors = " OR ".join(["model ILIKE %s"] * len(models))
        fragments.append(f"({ors})")
        params.extend(f"%{m}%" for m in models)

    # locations — exact multi-select
    locations = _multi_values(None, req.locations)
    if locations:
        placeholders = ", ".join(["%s"] * len(locations))
        fragments.append(f"location IN ({placeholders})")
        params.extend(locations)

    if req.customs_cleared is not None:
        fragments.append("customs_cleared = %s")
        params.append(req.customs_cleared)
    return fragments, params


def _sort_clause(sort: str | None) -> str:
    """ORDER BY tail string. Default = newest."""
    return _SORT_CLAUSES.get(sort or "newest", _SORT_CLAUSES["newest"])


def _has_any_filter(req: SearchRequest) -> bool:
    ranges = any(
        getattr(req, k) is not None
        for k in ("year_from", "year_to", "price_from", "price_to", "mileage_from", "mileage_to")
    )
    facets = any(getattr(req, k) for k in (
        "body_type", "fuel_type", "gearbox", "drive_wheels",
        "body_types", "fuels", "gearboxes", "drives",
        "manufacturers", "models", "locations",
    ))
    return ranges or facets or req.customs_cleared is not None


_PHONE_CHARS_RE = re.compile(r"[\d\s+()\-.]+")


def _looks_like_phone(text: str) -> bool:
    """7+ ციფრი + ფონის სიმბოლოები (digits, spaces, +, -, parens, dots)."""
    digits = re.sub(r"\D", "", text)
    if len(digits) < 7:
        return False
    if _PHONE_CHARS_RE.fullmatch(text):
        return True
    return len(digits) / len(text) > 0.5


def _paginate(where_sql: str, where_params: tuple, order_by: str,
              order_params: tuple, page: int) -> tuple[str, tuple]:
    """შედეგების გვერდი CTE-ით: id + total პატარა სვეტებზე ვიღებთ, შემდეგ სრულ
    row-ებს (description/ფოტოები TOAST-შია) მხოლოდ ამ 25-სთვის ვკითხულობთ —
    Supabase free-tier-ის ნელ დისკზე ბევრ-შედეგიან ძიებას მკვეთრად აჩქარებს."""
    offset = (page - 1) * PAGE_SIZE
    sql = (
        f"WITH ids AS (SELECT id, COUNT(*) OVER () AS _total FROM cars "
        f"WHERE {where_sql} ORDER BY {order_by} LIMIT {PAGE_SIZE} OFFSET {offset}) "
        f"SELECT c.*, ids._total FROM ids JOIN cars c ON c.id = ids.id ORDER BY {order_by}"
    )
    return sql, (*where_params, *order_params, *order_params)


def _smart_route(req: SearchRequest, text: str) -> tuple[str, tuple, str]:
    """Auto-detect VIN / phone / freeform text. Filters + sort apply to
    freeform/browse (VIN/phone are exact lookups — filters don't make sense)."""
    text = text.strip()
    if not text:
        return _browse_query(req)

    upper = text.upper()
    if _VIN_RE.match(upper):
        return _paginate("vin = %s", (upper,), "updated_at DESC", (), req.page) + ("vin",)

    if _looks_like_phone(text):
        suffix = _normalize_phone_query(text)
        return _paginate(
            "regexp_replace(phone, '\\D', '', 'g') LIKE %s", ("%" + suffix,),
            "updated_at DESC", (), req.page,
        ) + ("phone",)

    words = [w for w in text.split() if w]
    if not words or len(text) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "query_too_vague"},
        )

    word_clauses = " AND ".join([f"{_SEARCH_BLOB} LIKE %s"] * len(words))
    patterns = [f"%{w.lower()}%" for w in words]
    filter_frags, filter_params = _filter_clauses(req)
    extra_where = (" AND " + " AND ".join(filter_frags)) if filter_frags else ""
    where_sql = f"{word_clauses}{extra_where}"
    where_params = (*patterns, *filter_params)

    if req.sort:
        return _paginate(where_sql, where_params, _sort_clause(req.sort), (), req.page) + ("search",)
    order_by = f"similarity({_TITLE_BLOB}, %s) DESC NULLS LAST, updated_at DESC"
    return _paginate(where_sql, where_params, order_by, (text,), req.page) + ("search",)


def _browse_query(req: SearchRequest) -> tuple[str, tuple, str]:
    """No text — just filters + sort. e.g. all 2018-2022 cars under $20k."""
    if not _has_any_filter(req):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "query_empty"},
        )
    filter_frags, filter_params = _filter_clauses(req)
    where = " AND ".join(filter_frags)
    return _paginate(where, tuple(filter_params), _sort_clause(req.sort), (), req.page) + ("browse",)


def _build_query(req: SearchRequest) -> tuple[str, tuple, str]:
    """Routes to smart-search if `query` set, otherwise legacy logic, otherwise browse."""
    if req.query:
        return _smart_route(req, req.query)

    if req.vin and len(req.vin) == 17:
        return _paginate("vin = %s", (req.vin.upper(),), "updated_at DESC", (), req.page) + ("vin",)
    if req.vin:
        return _paginate("vin LIKE %s", (req.vin.upper() + "%",), "updated_at DESC", (), req.page) + ("vin",)
    if req.phone:
        suffix = _normalize_phone_query(req.phone)
        if len(suffix) < 4:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "phone_too_short"},
            )
        return _paginate(
            "regexp_replace(phone, '\\D', '', 'g') LIKE %s", ("%" + suffix,),
            "updated_at DESC", (), req.page,
        ) + ("phone",)
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
        price_amount=_clean_price(row.get("price_amount"), row.get("price_currency")),
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


# ერთიდაიგივე ძიების შედეგს ვაქეშებთ — Supabase free-tier-ის ნელი დისკი ერთხელ
# იკითხება, შემდეგ პოპულარული ძიება (BMW, Mercedes…) მყისიერია. TTL 10 წთ.
_RESULT_CACHE: "OrderedDict[str, tuple[float, list]]" = OrderedDict()
_RESULT_TTL = 600.0
_RESULT_CACHE_MAX = 600
# sync endpoint-ები threadpool-ში გადიან — ცვლა lock-ქვეშ, რომ eviction loop
# პარალელურ წვდომას არ გადაეჯაჭვოს.
_RESULT_CACHE_LOCK = threading.Lock()


def _cache_put(key: str, rows: list, now: float) -> None:
    """ქეშში ჩაწერა + capacity-ის შენარჩუნება. ზედმეტ ჩანაწერებს უძველესიდან
    ვაცლით (clear()-ის ნაცვლად), რომ პოპულარული ძიების ქეში ცივ-სტარტში
    ერთიანად არ დაიკარგოს."""
    with _RESULT_CACHE_LOCK:
        _RESULT_CACHE[key] = (now, rows)
        _RESULT_CACHE.move_to_end(key)
        while len(_RESULT_CACHE) > _RESULT_CACHE_MAX:
            _RESULT_CACHE.popitem(last=False)


def _query_rows(sql: str, params: tuple) -> list:
    key = sql + "\x00" + repr(params)
    now = time.monotonic()
    # read lock-ქვეშ — eviction-ი (move_to_end/popitem) რომ პარალელურ get-ს
    # არ გადაეჯაჭვოს. DB query lock-ის გარეთ რჩება (ძიება ხშირია, არ ვასერიალებთ).
    with _RESULT_CACHE_LOCK:
        hit = _RESULT_CACHE.get(key)
        if hit is not None and now - hit[0] < _RESULT_TTL:
            return hit[1]
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    _cache_put(key, rows, now)
    return rows


@router.post("", response_model=SearchResponse)
def search(req: SearchRequest, request: Request, background_tasks: BackgroundTasks) -> SearchResponse:
    """ძიება — VIN, ნომერი, ან თავისუფალი ტექსტი. სრულიად უფასო."""

    remaining = check_rate_limit(request, is_pagination=req.page > 1)

    sql, params, query_type = _build_query(req)
    rows = _query_rows(sql, params)

    total_count = int(rows[0]["_total"]) if rows else 0

    results = [_row_to_public(row) for row in rows]
    results_count = len(results)

    query_repr = req.query or req.vin or req.phone or req.free_text or ""
    background_tasks.add_task(log_search, request, query_repr, query_type, results_count)

    return SearchResponse(
        query_type=query_type,
        results=results,
        results_count=results_count,
        total_count=total_count,
        page=req.page,
        page_size=PAGE_SIZE,
        remaining_searches=remaining,
    )


def _count_where(req: SearchRequest) -> tuple[str, tuple]:
    """WHERE clause + params for the live count — mirrors the real search routing
    (VIN / phone / freeform text, each combined with the active filters) so the
    count always matches what a search would return."""
    text = (req.query or req.free_text or "").strip()
    frags, fparams = _filter_clauses(req)
    filter_tail = (" AND " + " AND ".join(frags)) if frags else ""

    if text:
        upper = text.upper()
        if _VIN_RE.match(upper):
            return "vin = %s" + filter_tail, (upper, *fparams)
        if _looks_like_phone(text):
            suffix = _normalize_phone_query(text)
            return (
                r"regexp_replace(phone, '\D', '', 'g') LIKE %s" + filter_tail,
                ("%" + suffix, *fparams),
            )
        words = [w for w in text.split() if w]
        if words and len(text) >= 2:
            word_clauses = " AND ".join([f"{_SEARCH_BLOB} LIKE %s"] * len(words))
            patterns = [f"%{w.lower()}%" for w in words]
            return word_clauses + filter_tail, (*patterns, *fparams)

    # no usable text — filters only
    return (" AND ".join(frags) if frags else ""), tuple(fparams)


@router.post("/count", response_model=SearchCount)
def search_count(req: SearchRequest) -> SearchCount:
    """Match count for the current query + filters — drives the live count on the
    search button. No rows, no rate limit; cached like searches."""
    where, params = _count_where(req)
    sql = "SELECT COUNT(*) AS n FROM cars" + (f" WHERE {where}" if where else "")
    rows = _query_rows(sql, params)
    return SearchCount(total_count=int(rows[0]["n"]) if rows else 0)


@car_router.get("/{key}", response_model=CarPublic)
def get_car(key: str, response: Response) -> CarPublic:
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
    response.headers["Cache-Control"] = "public, max-age=120"
    return _row_to_public(row)
