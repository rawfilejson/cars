# values behind the facet filters: body, fuel, gearbox and drive dropdowns

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

# response key -> table column. Hard-coded, so user input never reaches the SQL
_FIELDS = {
    "body_type": "body_type",
    "fuel": "engine_type",
    "gearbox": "gearbox",
    "drive": "drive_wheels",
    "location": "location",
}

# messy variant -> canonical value. The sources spell the same thing several ways
_CANON = {
    "ჰეჩბეკი": "ჰეტჩბეკი",
    "ჰეტჩბექი": "ჰეტჩბეკი",
    "ჰეჩბექი": "ჰეტჩბეკი",
    "ბენზინზე": "ბენზინი",
    "დიზელზე": "დიზელი",
    "4X4": "4x4",
}


def facet_canon(value: str) -> str:
    # reduce a raw value to its canonical form
    return _CANON.get(value, value)


def facet_variants(value: str) -> list[str]:
    # every raw spelling of a canonical value, for the IN clause in a filter
    out = [value] + [raw for raw, canon in _CANON.items() if canon == value]
    return list(dict.fromkeys(out))


class FacetsResponse(BaseModel):
    # {facet: [values]}, most common first

    facets: dict[str, list[str]]


def _load_facets() -> FacetsResponse:
    out = {}
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
                # fold duplicates into the canonical value, keeping the most-common-first order
                seen = {}
                for row in cur.fetchall():
                    seen.setdefault(facet_canon(row["v"]), None)
                out[key] = list(seen.keys())
    return FacetsResponse(facets=out)


@router.get("", response_model=FacetsResponse)
def get_facets(response: Response) -> FacetsResponse:
    # facet values, cached for an hour
    global _cache
    response.headers["Cache-Control"] = "public, max-age=3600"
    now = time.monotonic()
    # double-checked locking, so simultaneous cold-cache requests cause one DB load instead of a stampede
    # loads are rare anyway with an hourly TTL
    with _cache_lock:
        if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
            return _cache[1]
        data = _load_facets()
        _cache = (now, data)
        return data
