"""მწარმოებელი → მოდელების სია — ძიების dropdown მენიუსთვის."""

from __future__ import annotations

import time

from fastapi import APIRouter, Response
from pydantic import BaseModel

from src.api.db_pool import connection


router = APIRouter(prefix="/makes", tags=["makes"])

_CACHE_TTL_SECONDS = 3600.0
_MIN_COUNT = 3
_cache: tuple[float, "MakesResponse"] | None = None


class MakesResponse(BaseModel):
    """{მწარმოებელი: [მოდელები]} — ანბანის რიგზე."""

    makes: dict[str, list[str]]


def _load_makes() -> MakesResponse:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT manufacturer, model, COUNT(*) AS c
                FROM cars
                WHERE manufacturer <> '' AND model <> ''
                GROUP BY manufacturer, model
                HAVING COUNT(*) >= %s
                ORDER BY manufacturer, model
                """,
                (_MIN_COUNT,),
            )
            makes: dict[str, list[str]] = {}
            for row in cur.fetchall():
                makes.setdefault(row["manufacturer"], []).append(row["model"])
    return MakesResponse(makes=makes)


@router.get("", response_model=MakesResponse)
def get_makes(response: Response) -> MakesResponse:
    """მწარმოებელი → მოდელები. საათში ერთხელ ქეშდება (იშვიათად იცვლება)."""
    global _cache
    response.headers["Cache-Control"] = "public, max-age=3600"
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]
    data = _load_makes()
    _cache = (now, data)
    return data
