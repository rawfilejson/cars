# მწარმოებელი → მოდელების სია — ძიების dropdown მენიუსთვის.

from __future__ import annotations

import re
import threading
import time

from fastapi import APIRouter, Response
from pydantic import BaseModel

from src.api.db_pool import connection


router = APIRouter(prefix="/makes", tags=["makes"])

_CACHE_TTL_SECONDS = 3600.0
_MIN_COUNT = 3
_cache: tuple[float, "MakesResponse"] | None = None
_cache_lock = threading.Lock()

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
_TWO_WORD = {"land", "grand", "range", "santa", "alfa", "aston", "mini", "model", "great", "gran"}
_TRIM_NUM_RE = re.compile(r"(\d{2,3})[a-z]{1,2}")
# კლასის ნომერი (C 300, GLE 350, E 220d) — ეს submodel-ია და არა trim-ნაგავი
_SERIES_NUM_RE = re.compile(r"\d{2,3}[a-z]{0,2}", re.IGNORECASE)


def _canon_token(tok: str) -> str:
    # რიცხვით trim-ს ბაზურ ნომრამდე ამცირებს (320i/320d → 320).
    m = _TRIM_NUM_RE.fullmatch(tok)
    return m.group(1) if m else tok


def _base_model(manufacturer: str, model: str) -> str:
    # სრული trim-სტრიქონიდან ბაზური მოდელის სახელს გამოყოფს.
    model = re.sub(r"[×](?=\d)", "x", model)
    toks = [t for t in re.split(r"[\s/]+", model.strip())
            if t and t.lower() != manufacturer.lower()]
    if not toks:
        return ""
    take = 1
    low0 = toks[0].lower().strip("-")
    if len(toks) > 1:
        nxt = toks[1]
        if low0 in _TWO_WORD or toks[0].isdigit():
            if nxt.isascii() and nxt.isalpha() and len(nxt) >= 4 and nxt.lower() not in _JUNK:
                take = 2
        elif len(toks[0]) <= 3 and toks[0].isalpha() and _SERIES_NUM_RE.fullmatch(nxt):
            # ასოებიანი სერია + ნომერი (C 300) — ნომერი submodel-ს განასხვავებს
            take = 2
    return " ".join(_canon_token(t) for t in toks[:take])


class MakesResponse(BaseModel):
    # {მწარმოებელი: [მოდელები]} — პოპულარობის რიგზე (ყველაზე ბევრი → ნაკლები).

    makes: dict[str, list[str]]


def _order_makes(
    agg: dict[str, dict[str, tuple[str, int]]],
) -> dict[str, list[str]]:
    # აგრეგირებული count-ები → {მწარმოებელი: [მოდელები]} პოპულარობის რიგზე.
    #
    # მწარმოებლები — ყველაზე ბევრი განცხადება პირველი; თითოეულში მოდელებიც
    # count-ის კლებადობით (ტოლობისას ანბანურად). იშვიათი მოდელები ეთიშება,
    # მაგრამ ბრენდი განცხადებით ყოველთვის ჩანს — თუნდაც ერთი მანქანა იყოს.
    ranked: list[tuple[str, int, list[str]]] = []
    for manu, bucket in agg.items():
        kept = [(disp, cnt) for disp, cnt in bucket.values() if cnt >= _MIN_COUNT]
        if not kept:
            kept = list(bucket.values())
        if not kept:
            continue
        kept.sort(key=lambda dc: (-dc[1], dc[0].lower()))
        total = sum(cnt for _, cnt in kept)
        ranked.append((manu, total, [disp for disp, _ in kept]))
    ranked.sort(key=lambda mt: (-mt[1], mt[0].lower()))
    return {manu: models for manu, _total, models in ranked}


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

    # იშვიათი ნომრიანი submodel-ი (cnt < _MIN_COUNT) კლასის ბაზურ ჩანაწერში ბრუნდება,
    # რომ ეს მანქანები კლასის ფილტრით მაინც იძებნებოდეს
    for bucket in agg.values():
        rare = [k for k, (disp, cnt) in bucket.items()
                if cnt < _MIN_COUNT and " " in disp and disp.split()[1].isdigit()]
        for k in rare:
            disp, cnt = bucket.pop(k)
            base = disp.split()[0]
            bkey = base.lower().replace("-", "")
            bdisp, bcnt = bucket.get(bkey, (base, 0))
            bucket[bkey] = (bdisp, bcnt + cnt)

    return MakesResponse(makes=_order_makes(agg))


@router.get("", response_model=MakesResponse)
def get_makes(response: Response) -> MakesResponse:
    # მწარმოებელი → მოდელები. საათში ერთხელ ქეშდება (იშვიათად იცვლება).
    global _cache
    response.headers["Cache-Control"] = "public, max-age=3600"
    now = time.monotonic()
    # double-checked locking — ერთდროული cold-cache request-ები ერთ DB load-ს
    # აკეთებენ (stampede-ის ნაცვლად). load იშვიათია (საათობრივი TTL).
    with _cache_lock:
        if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
            return _cache[1]
        data = _load_makes()
        _cache = (now, data)
        return data
