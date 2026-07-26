# A quick parser check against a handful of cars.
#
# run:
#     uv run python -m src.scripts.test_parser --limit 5
#
# This does not replace a full run; it just confirms the pipeline works end to
# end (links -> scrape -> database).

from __future__ import annotations

import argparse
import asyncio
import time

from playwright.async_api import async_playwright

from src.common.anti_detection import block_heavy_resources, create_stealth_context
from src.common.config import CONCURRENT_PAGES
from src.common.db import upsert_cars
from src.parsers.autopapa import HOST, START_URL, scrape_one


async def main(limit: int) -> None:
    print(f"testing on {limit} cars...")
    start = time.time()

    async with async_playwright() as playwright:
        browser, context = await create_stealth_context(playwright)
        try:
            page = await context.new_page()
            await page.route("**/*", block_heavy_resources)
            await page.goto(START_URL, wait_until="domcontentloaded")
            await page.wait_for_selector("div.boxCatalog2")

            test_links: list[str] = []
            for anchor in await page.query_selector_all("a.with_hash2"):
                href = await anchor.get_attribute("href")
                if href:
                    test_links.append(HOST + href.split("?")[0])
                    if len(test_links) >= limit:
                        break
            await page.close()
            print(f"links from the first page: {len(test_links)}")

            semaphore = asyncio.Semaphore(CONCURRENT_PAGES)
            results = await asyncio.gather(
                *[scrape_one(context, url, semaphore) for url in test_links]
            )

            cars = [c for c in results if c is not None]
            print(f"\nscraped: {len(cars)}/{len(test_links)}")

            for car in cars:
                print(
                    f"  - {car.source_id} | {car.manufacturer} {car.model} | "
                    f"{car.year} | {car.price_amount} {car.price_currency} | "
                    f"VIN: {car.vin or '<empty>'} | "
                    f"photos: {len(car.image_urls)} | "
                    f"phone: {car.phone or '<empty>'}"
                )

            if cars:
                saved = await upsert_cars(cars)
                print(f"\nwritten to the database: {saved}")

        finally:
            await context.close()
            await browser.close()

    print(f"\ntest finished in {time.time() - start:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    from src.common.runtime import run

    run(main(args.limit))
