"""ფასეტ-ფილტრების მნიშვნელობები — ძარა/საწვავი/კოლოფი/წამყვანი dropdown-ებისთვის."""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Response
from pydantic import BaseModel

from src.api.db_pool import connection


router = APIRouter(prefix="/facets", tags=["facets"])

_CACHE_TTL_SECONDS = 3600.0
_MIN_COUNT = 5
_cache: tuple[float, "FacetsResponse"] | None = None
_cache_lock = threading.Lock()

# პასუხის key → ცხრილის სვეტი (ფიქსირებული — user input არ ერევა SQL-ში)
_FIELDS = {
    "body_type": "body_type",
    "fuel": "engine_type",
    "gearbox": "gearbox",
    "drive": "drive_wheels",
    "location": "location",
}

# ბინძური variant → კანონიკური მნიშვნელობა (ბაზაში ერთი და იგივე რამდენ ნაირად წერია)
_CANON = {
    "ჰეჩბეკი": "ჰეტჩბეკი",
    "ჰეტჩბექი": "ჰეტჩბეკი",
    "ჰეჩბექი": "ჰეტჩბეკი",
    "ბენზინზე": "ბენზინი",
    "დიზელზე": "დიზელი",
    "4X4": "4x4",
}


def facet_canon(value: str) -> str:
    """raw მნიშვნელობას კანონიკურამდე ამცირებს."""
    return _CANON.get(value, value)


def facet_variants(value: str) -> list[str]:
    """კანონიკურ მნიშვნელობას უბრუნებს ყველა raw variant-ს (ფილტრში IN-ისთვის)."""
    out = [value] + [raw for raw, canon in _CANON.items() if canon == value]
    return list(dict.fromkeys(out))


class FacetsResponse(BaseModel):
    """{facet: [მნიშვნელობები]} — სიხშირის მიხედვით."""

    facets: dict[str, list[str]]


def _load_facets() -> FacetsResponse:
    out: dict[str, list[str]] = {}
    with connection() as conn:
        with conn.cursor() as cur:
            for key, col in _FIELDS.items():
                cur.execute(
                    f"""
                    SELECT {col} AS v, COUNT(*) AS c
                    FROM cars
                    WHERE {col} IS NOT NULL AND {col} <> ''
                    GROUP BY {col}
                    HAVING COUNT(*) >= %s
                    ORDER BY c DESC
                    """,
                    (_MIN_COUNT,),
                )
                # კანონიკურამდე ვაერთიანებთ duplicate-ებს, სიხშირის რიგი რჩება
                seen: dict[str, None] = {}
                for row in cur.fetchall():
                    seen.setdefault(facet_canon(row["v"]), None)
                out[key] = list(seen.keys())
    return FacetsResponse(facets=out)


@router.get("", response_model=FacetsResponse)
def get_facets(response: Response) -> FacetsResponse:
    """ფასეტ-მნიშვნელობები. საათში ერთხელ ქეშდება."""
    global _cache
    response.headers["Cache-Control"] = "public, max-age=3600"
    now = time.monotonic()
    # double-checked locking — ერთდროული cold-cache request-ები ერთ DB load-ს
    # აკეთებენ (stampede-ის ნაცვლად). load იშვიათია (საათობრივი TTL).
    with _cache_lock:
        if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
            return _cache[1]
        data = _load_facets()
        _cache = (now, data)
        return data
