"""ფასეტ-ფილტრების მნიშვნელობები — ძარა/საწვავი/კოლოფი/წამყვანი dropdown-ებისთვის."""

from __future__ import annotations

import time

from fastapi import APIRouter, Response
from pydantic import BaseModel

from src.api.db_pool import connection


router = APIRouter(prefix="/facets", tags=["facets"])

_CACHE_TTL_SECONDS = 3600.0
_MIN_COUNT = 5
_cache: tuple[float, "FacetsResponse"] | None = None

# პასუხის key → ცხრილის სვეტი (ფიქსირებული — user input არ ერევა SQL-ში)
_FIELDS = {
    "body_type": "body_type",
    "fuel": "engine_type",
    "gearbox": "gearbox",
    "drive": "drive_wheels",
}


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
                out[key] = [row["v"] for row in cur.fetchall()]
    return FacetsResponse(facets=out)


@router.get("", response_model=FacetsResponse)
def get_facets(response: Response) -> FacetsResponse:
    """ფასეტ-მნიშვნელობები. საათში ერთხელ ქეშდება."""
    global _cache
    response.headers["Cache-Control"] = "public, max-age=3600"
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]
    data = _load_facets()
    _cache = (now, data)
    return data
