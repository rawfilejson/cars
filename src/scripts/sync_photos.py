"""
ფოტოების სინქრონიზაცია — ბაზიდან წავიკითხავთ image_urls-ს, რომ ჯერ ვერ
ჩატვირთული ფოტოები ჩავტვირთოთ ლოკალურად + R2-ში.

გაშვება:
    python -m src.scripts.sync_photos              # ყველა მანქანა
    python -m src.scripts.sync_photos --source autopapa --limit 100

რა ხდება:
  1. ბაზიდან ვირჩევთ მანქანებს რომელთა image_keys ჯერ ცარიელია.
  2. თითო მანქანის image_urls-ს ვტვირთავთ ლოკალურ photos/ ფოლდერში.
  3. თუ R2 კონფიგურირებულია — იქაც ვტვირთავთ.
  4. ბაზაში ვაახლებთ image_keys-ს (ლისტი key-ების).
"""

from __future__ import annotations

import argparse
import asyncio
import time

import httpx
import psycopg

from src.common.config import DATABASE_URL, r2_is_configured
from src.common.db import update_image_keys
from src.common.storage import fetch_and_store


def fetch_pending_sync(
    source: str | None, limit: int | None
) -> list[tuple[int, str, str, list[str]]]:
    """ბაზიდან მანქანები რომელთა image_keys ცარიელია, მაგრამ image_urls გვაქვს."""
    query = """
        SELECT id, source, source_id, image_urls
        FROM cars
        WHERE image_urls IS NOT NULL
          AND array_length(image_urls, 1) > 0
          AND (image_keys IS NULL OR array_length(image_keys, 1) IS NULL)
    """
    params: list = []

    if source:
        query += " AND source = %s"
        params.append(source)

    query += " ORDER BY id"

    if limit:
        query += " LIMIT %s"
        params.append(limit)

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return list(cur.fetchall())


async def fetch_pending(
    source: str | None, limit: int | None
) -> list[tuple[int, str, str, list[str]]]:
    return await asyncio.to_thread(fetch_pending_sync, source, limit)


async def _fetch_one(
    http_client: httpx.AsyncClient,
    photo_sem: asyncio.Semaphore,
    source: str,
    source_id: str,
    index: int,
    url: str,
    upload_to_cloud: bool,
    keep_local: bool,
) -> str | None:
    """ერთი ფოტო — never raises. photo_sem ზღუდავს ერთდროულ I/O-ს."""
    async with photo_sem:
        try:
            return await fetch_and_store(
                http_client, url, source, source_id, index,
                upload_to_cloud=upload_to_cloud,
                keep_local=keep_local,
            )
        except Exception as exc:
            print(f"  [skip photo] {source}/{source_id}/{index}: {type(exc).__name__}")
            return None


async def process_car(
    http_client: httpx.AsyncClient,
    photo_sem: asyncio.Semaphore,
    car_db_id: int,
    source: str,
    source_id: str,
    image_urls: list[str],
    upload_to_cloud: bool,
    keep_local: bool = True,
) -> int:
    """ერთი მანქანის ფოტოები პარალელურად — never raises, always returns int.

    gather თანმიმდევრობას ინახავს, ამიტომ key-ები ფოტოს index-ის რიგზე რჩება;
    ჩავარდნილი ფოტო None-ია და ისე იჭრება.
    """
    results = await asyncio.gather(*(
        _fetch_one(
            http_client, photo_sem, source, source_id, index, url,
            upload_to_cloud, keep_local,
        )
        for index, url in enumerate(image_urls, start=1)
    ))
    keys = [key for key in results if key]

    if keys:
        try:
            await update_image_keys(car_db_id, keys)
        except Exception as exc:
            print(f"  [skip DB update] {source}/{source_id}: {type(exc).__name__}")
    return len(keys)


async def main() -> None:
    parser = argparse.ArgumentParser(description="ფოტოების სინქრონიზაცია")
    parser.add_argument("--source", help="მხოლოდ ერთი წყაროდან (autopapa/myauto)")
    parser.add_argument("--limit", type=int, help="რამდენი მანქანა მაქსიმუმ")
    parser.add_argument(
        "--concurrent", type=int, default=8,
        help="ერთდროული ფოტოს download/upload-ების რაოდენობა (I/O bound)",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="მხოლოდ ლოკალურად — R2-ში არ ატვირთო",
    )
    parser.add_argument(
        "--purge-local",
        action="store_true",
        help="R2-ში წარმატებული upload-ის შემდეგ ლოკალური ფაილი წაიშლება "
             "(disk-constrained backfill — runner-ს დისკი არ ევსება)",
    )
    args = parser.parse_args()

    upload_to_cloud = (not args.local_only) and r2_is_configured()
    if not args.local_only and not r2_is_configured():
        print("R2 არ არის კონფიგურირებული — მხოლოდ ლოკალურად ვინახავთ.")

    if args.purge_local and not upload_to_cloud:
        raise SystemExit(
            "--purge-local მოითხოვს R2 upload-ს. --local-only-სთან ან "
            "R2-ის კონფიგურაციის გარეშე უარს ვამბობთ (backup-ის გარეშე წაშლა საშიშია)."
        )
    keep_local = not args.purge_local

    pending = await fetch_pending(args.source, args.limit)
    print(f"დასამუშავებელი მანქანები: {len(pending)}")

    if not pending:
        return

    start = time.time()
    total = len(pending)
    total_photos = 0
    done = 0

    photo_sem = asyncio.Semaphore(args.concurrent)
    queue: asyncio.Queue = asyncio.Queue()
    for car in pending:
        queue.put_nowait(car)

    async with httpx.AsyncClient(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
        follow_redirects=True,
    ) as client:

        async def worker() -> None:
            nonlocal total_photos, done
            while True:
                try:
                    car_id, source, source_id, urls = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                n_photos = await process_car(
                    client, photo_sem, car_id, source, source_id, urls,
                    upload_to_cloud, keep_local,
                )
                total_photos += n_photos
                done += 1
                if done % 10 == 0 or done == total:
                    elapsed = time.time() - start
                    rate = done / elapsed if elapsed else 0
                    print(f"[{done}/{total}] photos:{total_photos} rate:{rate:.1f} car/s")

        await asyncio.gather(*(worker() for _ in range(args.concurrent)))

    print(f"\nდასრულდა. ფოტოები: {total_photos}, დრო: {time.time() - start:.0f} წმ.")


if __name__ == "__main__":
    from src.common.runtime import run

    run(main())
