# stats endpoint: total number of cars and a breakdown by source

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Response
from pydantic import BaseModel

from src.api.db_pool import connection


router = APIRouter(prefix="/stats", tags=["stats"])

_CACHE_TTL_SECONDS = 60.0
_cache: tuple[float, "Stats"] | None = None
_cache_lock = threading.Lock()


class Stats(BaseModel):
    # the totals shown in the site header

    total_cars: int
    by_source: dict[str, int]
    with_vin: int
    with_photos: int


def _get_stats_sync() -> Stats:
    # one query for all of it
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE vin <> '' AND vin IS NOT NULL) AS with_vin,
                    COUNT(*) FILTER (WHERE image_keys IS NOT NULL
                                     AND array_length(image_keys, 1) > 0) AS with_photos
                FROM cars
                """
            )
            row = cur.fetchone()
            total, with_vin, with_photos = row["total"], row["with_vin"], row["with_photos"]

            cur.execute(
                "SELECT source, COUNT(*) AS c FROM cars GROUP BY source ORDER BY source"
            )
            by_source = {r["source"]: int(r["c"]) for r in cur.fetchall()}

    return Stats(
        total_cars=total,
        by_source=by_source,
        with_vin=with_vin,
        with_photos=with_photos,
    )


@router.get("", response_model=Stats)
def get_stats(response: Response) -> Stats:
    # overall stats, cached so we don't run a COUNT on every page load
    global _cache
    response.headers["Cache-Control"] = "public, max-age=60"
    now = time.monotonic()
    # double-checked locking, so simultaneous cold-cache requests cause one COUNT
    # rather than a stampede. Loads are rare anyway with a 60s TTL.
    with _cache_lock:
        if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
            return _cache[1]
        stats = _get_stats_sync()
        _cache = (now, stats)
        return stats
