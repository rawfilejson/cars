"""მწარმოებელი → მოდელების სია — ძიების dropdown მენიუსთვის."""

from __future__ import annotations

import re
import time

from fastapi import APIRouter, Response
from pydantic import BaseModel

from src.api.db_pool import connection


router = APIRouter(prefix="/makes", tags=["makes"])

_CACHE_TTL_SECONDS = 3600.0
_MIN_COUNT = 3
_cache: tuple[float, "MakesResponse"] | None = None

# trim/ძარა/გადაცემათა-კოლოფის სიტყვები, რაც მოდელის სახელის ნაწილი არ არის
_JUNK = {
    "sedan", "suv", "coupe", "hatchback", "wagon", "van", "minivan", "pickup",
    "truck", "convertible", "crossover", "cross", "automatic", "manual", "cvt",
    "auto", "tiptronic", "hybrid", "phev", "plug-in", "plugin", "diesel", "petrol",
    "awd", "fwd", "rwd", "4wd", "2wd", "4matic", "quattro", "xdrive", "sport",
    "premium", "luxury", "limited", "platinum", "touring", "trail", "nightshade",
    "anniversary", "edition", "special", "sr5", "xle", "xse", "trd", "ggs",
    "front-wheel", "all-wheel", "rear-wheel", "drive", "iperformance", "base",
    "full", "competition", "active", "efficient", "line",
}
_DRIVE_RE = re.compile(r"^\d?x\d$|^\d(dr|wd)$|^4x[24]$|^v\d$", re.IGNORECASE)
_TWO_WORD = {"land", "grand", "range", "santa", "alfa", "aston", "mini", "model", "great", "gran"}
_TRIM_NUM_RE = re.compile(r"(\d{2,3})[a-z]{1,2}")


def _canon_token(tok: str) -> str:
    """რიცხვით trim-ს ბაზურ ნომრამდე ამცირებს (320i/320d → 320)."""
    m = _TRIM_NUM_RE.fullmatch(tok)
    return m.group(1) if m else tok


def _base_model(manufacturer: str, model: str) -> str:
    """სრული trim-სტრიქონიდან ბაზური მოდელის სახელს გამოყოფს."""
    model = re.sub(r"[×](?=\d)", "x", model)
    toks = [t for t in re.split(r"[\s/]+", model.strip())
            if t and t.lower() != manufacturer.lower()]
    if not toks:
        return ""
    take = 1
    low0 = toks[0].lower().strip("-")
    if (low0 in _TWO_WORD or toks[0].isdigit()) and len(toks) > 1:
        nxt = toks[1]
        if nxt.isascii() and nxt.isalpha() and len(nxt) >= 4 and nxt.lower() not in _JUNK:
            take = 2
    return " ".join(_canon_token(t) for t in toks[:take])


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
                """,
            )
            rows = cur.fetchall()

    # ბაზურ მოდელამდე ვამცირებთ, duplicate-ებს ვაერთიანებთ და რაოდენობას ვაჯამებთ
    agg: dict[str, dict[str, tuple[str, int]]] = {}
    for row in rows:
        manu = row["manufacturer"]
        base = _base_model(manu, row["model"])
        if not base:
            continue
        key = base.lower().replace(" ", "").replace("-", "")
        bucket = agg.setdefault(manu, {})
        disp, cnt = bucket.get(key, (base, 0))
        bucket[key] = (disp, cnt + row["c"])

    makes: dict[str, list[str]] = {}
    for manu, bucket in agg.items():
        models = sorted(
            (disp for disp, cnt in bucket.values() if cnt >= _MIN_COUNT),
            key=str.lower,
        )
        if models:
            makes[manu] = models
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
