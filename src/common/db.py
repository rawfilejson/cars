# Talking to PostgreSQL.
#
# There is a conflict on Windows: Playwright needs the ProactorEventLoop for
# subprocesses, while async psycopg needs the SelectorEventLoop. They cannot run
# together, so this uses sync psycopg and pushes each call onto its own thread
# with asyncio.to_thread. From the outside the API is still async.
#
# The main entry points:
#   * get_existing_ids(source) - ids we already stored, so a run can resume
#   * upsert_cars(cars) - write a whole batch at once

from __future__ import annotations

import asyncio
import atexit
from collections.abc import Iterable

from psycopg_pool import ConnectionPool

from .config import DATABASE_URL
from .models import Car


_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=2, open=True, timeout=30.0)
        atexit.register(_pool.close)
    return _pool


def _get_existing_ids_sync(source: str) -> set[str]:
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT source_id FROM cars WHERE source = %s", (source,))
            return {row[0] for row in cur.fetchall()}


def _count_cars_sync(source: str | None) -> int:
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            if source:
                cur.execute("SELECT COUNT(*) FROM cars WHERE source = %s", (source,))
            else:
                cur.execute("SELECT COUNT(*) FROM cars")
            row = cur.fetchone()
            return int(row[0]) if row else 0


_UPSERT_SQL = """
INSERT INTO cars (
    source, source_id, url,
    manufacturer, model, year, body_type,
    price_amount, price_currency, price_with_customs,
    engine_volume_l, engine_type, cylinders, power_hp, has_turbo,
    gearbox, drive_wheels,
    mileage_km, color, doors, seats, interior_color, interior_material,
    steering, condition, customs_cleared, has_catalyst, tech_inspection,
    vin, license_plate,
    location, seller_name, phone,
    posted_date, views,
    description, video_url, image_urls, image_keys
) VALUES (
    %(source)s, %(source_id)s, %(url)s,
    %(manufacturer)s, %(model)s, %(year)s, %(body_type)s,
    %(price_amount)s, %(price_currency)s, %(price_with_customs)s,
    %(engine_volume_l)s, %(engine_type)s, %(cylinders)s, %(power_hp)s, %(has_turbo)s,
    %(gearbox)s, %(drive_wheels)s,
    %(mileage_km)s, %(color)s, %(doors)s, %(seats)s, %(interior_color)s, %(interior_material)s,
    %(steering)s, %(condition)s, %(customs_cleared)s, %(has_catalyst)s, %(tech_inspection)s,
    %(vin)s, %(license_plate)s,
    %(location)s, %(seller_name)s, %(phone)s,
    %(posted_date)s, %(views)s,
    %(description)s, %(video_url)s, %(image_urls)s, %(image_keys)s
)
ON CONFLICT (source, source_id) DO UPDATE SET
    url                = EXCLUDED.url,
    manufacturer       = EXCLUDED.manufacturer,
    model              = EXCLUDED.model,
    year               = EXCLUDED.year,
    body_type          = EXCLUDED.body_type,
    price_amount       = EXCLUDED.price_amount,
    price_currency     = EXCLUDED.price_currency,
    price_with_customs = EXCLUDED.price_with_customs,
    engine_volume_l    = EXCLUDED.engine_volume_l,
    engine_type        = EXCLUDED.engine_type,
    cylinders          = EXCLUDED.cylinders,
    power_hp           = EXCLUDED.power_hp,
    has_turbo          = EXCLUDED.has_turbo,
    gearbox            = EXCLUDED.gearbox,
    drive_wheels       = EXCLUDED.drive_wheels,
    mileage_km         = EXCLUDED.mileage_km,
    color              = EXCLUDED.color,
    doors              = EXCLUDED.doors,
    seats              = EXCLUDED.seats,
    interior_color     = EXCLUDED.interior_color,
    interior_material  = EXCLUDED.interior_material,
    steering           = EXCLUDED.steering,
    condition          = EXCLUDED.condition,
    customs_cleared    = EXCLUDED.customs_cleared,
    has_catalyst       = EXCLUDED.has_catalyst,
    tech_inspection    = EXCLUDED.tech_inspection,
    -- keep the existing VIN when the new one is empty; a VIN we have seen once is worth holding on to
    vin                = COALESCE(NULLIF(EXCLUDED.vin, ''), cars.vin),
    license_plate      = COALESCE(NULLIF(EXCLUDED.license_plate, ''), cars.license_plate),
    location           = EXCLUDED.location,
    seller_name        = EXCLUDED.seller_name,
    phone              = COALESCE(NULLIF(EXCLUDED.phone, ''), cars.phone),
    posted_date        = EXCLUDED.posted_date,
    views              = EXCLUDED.views,
    description        = EXCLUDED.description,
    video_url          = EXCLUDED.video_url,
    image_urls         = EXCLUDED.image_urls,
    image_keys         = COALESCE(NULLIF(EXCLUDED.image_keys, '{}'), cars.image_keys)
"""


def _car_to_params(car: Car) -> dict:
    # turn the model into a dict matching the SQL placeholders
    data = car.model_dump()
    data.setdefault("image_urls", [])
    data.setdefault("image_keys", [])
    return data


def _upsert_cars_sync(cars_list: list[Car]) -> int:
    if not cars_list:
        return 0

    params = [_car_to_params(c) for c in cars_list]

    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(_UPSERT_SQL, params)
        conn.commit()

    return len(cars_list)


def _update_image_keys_sync(car_db_id: int, keys: list[str]) -> None:
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE cars SET image_keys = %s WHERE id = %s",
                (keys, car_db_id),
            )
        conn.commit()


async def get_existing_ids(source: str) -> set[str]:
    # source_ids we already have, so an interrupted run can pick up where it stopped
    #
    # If a script died halfway through, the next run knows these cars are already
    # stored and skips them.
    return await asyncio.to_thread(_get_existing_ids_sync, source)


async def count_cars(source: str | None = None) -> int:
    # how many cars we have in total, or from one source
    return await asyncio.to_thread(_count_cars_sync, source)


async def upsert_cars(cars: Iterable[Car]) -> int:
    # insert many cars in a single transaction
    return await asyncio.to_thread(_upsert_cars_sync, list(cars))


async def upsert_car(car: Car) -> None:
    # insert a single car; convenience wrapper
    await asyncio.to_thread(_upsert_cars_sync, [car])


async def update_image_keys(car_db_id: int, keys: list[str]) -> None:
    # store the R2 keys for a car's photos
    await asyncio.to_thread(_update_image_keys_sync, car_db_id, keys)
