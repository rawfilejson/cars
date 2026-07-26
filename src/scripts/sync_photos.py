# Photo sync: read image_urls from the database and fetch anything not yet
# downloaded, storing it locally and in R2.
#
# run:
#     python -m src.scripts.sync_photos              # every car
#     python -m src.scripts.sync_photos --source autopapa --limit 100
#
# What it does:
#   1. pick the cars whose image_keys are still empty
#   2. download each car's image_urls into the local photos/ folder
#   3. upload them to R2 as well, when R2 is configured
#   4. write the list of keys back into image_keys

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
    source: str | None, limit: int | None, shard: tuple[int, int] | None = None
) -> list[tuple[int, str, str, list[str]]]:
    # cars that still have no image_keys but do have image_urls
    #
    # shard=(x, n) takes only the cars where id %% n == x. That is how the parallel
    # blitz splits work across n runners without overlap.
    query = """
        SELECT id, source, source_id, image_urls
        FROM cars
        WHERE image_urls IS NOT NULL
          AND array_length(image_urls, 1) > 0
          AND (image_keys IS NULL OR array_length(image_keys, 1) IS NULL)
    """
    params = []

    if source:
        query += " AND source = %s"
        params.append(source)

    if shard:
        x, n = shard
        query += " AND MOD(id, %s) = %s"
        params.extend([n, x])

    query += " ORDER BY id"

    if limit:
        query += " LIMIT %s"
        params.append(limit)

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return list(cur.fetchall())


async def fetch_pending(
    source: str | None, limit: int | None, shard: tuple[int, int] | None = None
) -> list[tuple[int, str, str, list[str]]]:
    return await asyncio.to_thread(fetch_pending_sync, source, limit, shard)


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
    # one photo, never raises. photo_sem caps how much I/O runs at once
    async with photo_sem:
        try:
            return await fetch_and_store(
                http_client,
                url,
                source,
                source_id,
                index,
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
    # one car's photos in parallel. never raises, always returns an int
    #
    # gather preserves order, so the keys stay in photo order and a failed photo
    # comes back as None and is dropped.
    results = await asyncio.gather(
        *(
            _fetch_one(
                http_client,
                photo_sem,
                source,
                source_id,
                index,
                url,
                upload_to_cloud,
                keep_local,
            )
            for index, url in enumerate(image_urls, start=1)
        )
    )
    keys = [key for key in results if key]

    if keys:
        try:
            await update_image_keys(car_db_id, keys)
        except Exception as exc:
            print(f"  [skip DB update] {source}/{source_id}: {type(exc).__name__}")
    return len(keys)


async def main() -> None:
    parser = argparse.ArgumentParser(description="sync photos to local disk and R2")
    parser.add_argument("--source", help="only this source (autopapa/myauto)")
    parser.add_argument("--limit", type=int, help="maximum number of cars")
    parser.add_argument(
        "--concurrent",
        type=int,
        default=8,
        help="how many photo downloads/uploads to run at once (I/O bound)",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="store locally only, do not upload to R2",
    )
    parser.add_argument(
        "--purge-local",
        action="store_true",
        help="delete the local file once R2 confirms the upload, so a "
        "disk-constrained backfill does not fill up the runner",
    )
    parser.add_argument(
        "--shard",
        help="X/N: only cars where id %% N == X, for the parallel blitz",
    )
    args = parser.parse_args()

    shard: tuple[int, int] | None = None
    if args.shard:
        x_str, _, n_str = args.shard.partition("/")
        shard = (int(x_str), int(n_str))
        if not 0 <= shard[0] < shard[1]:
            raise SystemExit(f"--shard X/N needs 0 <= X < N (got {args.shard})")

    upload_to_cloud = (not args.local_only) and r2_is_configured()
    if not args.local_only and not r2_is_configured():
        print("R2 is not configured, storing photos locally only")

    if args.purge_local and not upload_to_cloud:
        raise SystemExit(
            "--purge-local needs R2 uploads to be on. Refusing to run with "
            "--local-only or without R2 configured, because deleting without a backup is dangerous."
        )
    keep_local = not args.purge_local

    pending = await fetch_pending(args.source, args.limit, shard)
    print(f"cars to process: {len(pending)}")

    if not pending:
        return

    start = time.time()
    total = len(pending)
    total_photos = 0
    done = 0

    photo_sem = asyncio.Semaphore(args.concurrent)
    queue = asyncio.Queue()
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
                    client,
                    photo_sem,
                    car_id,
                    source,
                    source_id,
                    urls,
                    upload_to_cloud,
                    keep_local,
                )
                total_photos += n_photos
                done += 1
                if done % 100 == 0 or done == total:
                    print(f"{done}/{total} cars, {total_photos} photos")

        await asyncio.gather(*(worker() for _ in range(args.concurrent)))

    print(f"\ndone, {total_photos} photos in {time.time() - start:.0f}s")


if __name__ == "__main__":
    from src.common.runtime import run

    run(main())
