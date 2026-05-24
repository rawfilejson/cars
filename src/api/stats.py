"""
სტატისტიკის endpoint — total cars count, sources breakdown.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from src.api.db_pool import connection


router = APIRouter(prefix="/stats", tags=["stats"])


class Stats(BaseModel):
    """საერთო რაოდენობები — ვებსაიტის header-ისთვის."""

    total_cars: int
    by_source: dict[str, int]
    with_vin: int
    with_photos: int


def _get_stats_sync() -> Stats:
    """ერთი query — ყველაფერი."""
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
def get_stats() -> Stats:
    """საერთო სტატისტიკა — ვებსაიტის გვერდის header-ისთვის."""
    return _get_stats_sync()
