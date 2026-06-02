"""
პარსერის სწრაფი ტესტი — მცირე რაოდენობის მანქანებზე.

გაშვება:
    uv run python -m src.scripts.test_parser --limit 5

ეს არ ცვლის სრულ parser-ს — უბრალოდ ვამოწმებთ პიპლაინი მუშაობს თუ არა
სრულად (links → scrape → DB).
"""

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
    print(f"ტესტი {limit} მანქანაზე...")
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
            print(f"ლინკები პირველი გვერდიდან: {len(test_links)}")

            semaphore = asyncio.Semaphore(CONCURRENT_PAGES)
            results = await asyncio.gather(
                *[scrape_one(context, url, semaphore) for url in test_links]
            )

            cars = [c for c in results if c is not None]
            print(f"\nსცრაიფული: {len(cars)}/{len(test_links)}")

            for car in cars:
                print(
                    f"  - {car.source_id} | {car.manufacturer} {car.model} | "
                    f"{car.year} | {car.price_amount} {car.price_currency} | "
                    f"VIN: {car.vin or '<empty>'} | "
                    f"ფოტო: {len(car.image_urls)} | "
                    f"ტელ: {car.phone or '<empty>'}"
                )

            if cars:
                saved = await upsert_cars(cars)
                print(f"\nDB-ში ჩაიწერა: {saved}")

        finally:
            await context.close()
            await browser.close()

    print(f"\nტესტი დასრულდა: {time.time() - start:.1f} წმ.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    from src.common.runtime import run

    run(main(args.limit))
