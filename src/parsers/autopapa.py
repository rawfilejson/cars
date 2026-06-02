"""Scraper for autopapa.ge listings.

We use Playwright (not plain HTTP) because the VIN reveal needs a click,
and the price-with-customs block is rendered after page load.

Flow:
  1. Walk through the search results paginating with the `next` button.
  2. For each listing URL, open the detail page and pull out everything.
  3. Batch-insert into Postgres (ON CONFLICT updates existing rows).
"""

from __future__ import annotations

import asyncio
import re
import time

from playwright.async_api import BrowserContext, Page, async_playwright

from src.common.anti_detection import block_heavy_resources, create_stealth_context
from src.common.config import CONCURRENT_PAGES, PAGE_TIMEOUT_MS, RETRY_PER_CAR
from src.common.csv_export import append_cars_to_csv
from src.common.db import get_existing_ids, upsert_cars
from src.common.models import Car
from src.common.normalize import (
    clean_engine_volume,
    clean_int,
    clean_text,
    format_phone,
    normalize_steering,
    parse_customs,
    sane_int,
    split_price,
)
from src.common import robots
from src.common.validators import validate_car
from src.common.vin import best_vin


SOURCE = "autopapa"
HOST = "https://autopapa.ge"
START_URL = "https://autopapa.ge/ge/usd/search?order=date&page=1"


_ID_FROM_URL_RE = re.compile(r"/(\d+)(?:[?#]|$)")


def extract_id(url: str) -> str:
    match = _ID_FROM_URL_RE.search(url)
    return match.group(1) if match else ""


def first_int(text: str | None) -> int | None:
    """First integer in `text`. "4/5" → 4, "26 000 კმ" → 26000."""
    if not text:
        return None
    s = str(text)
    match = re.search(r"\d", s)
    if not match:
        return None
    tail = re.match(r"[\d\s]+", s[match.start():])
    digits = re.sub(r"\D", "", tail.group(0)) if tail else match.group(0)
    return int(digits) if digits else None


def parse_features(text: str | None) -> dict[str, str]:
    """`.comment-all` reads "feature1, key: value, feature2, ..." — pull the key:value pairs.

    Plain features (ABS, ESP) are skipped here; they show up in the description text instead.
    """
    if not text:
        return {}
    result: dict[str, str] = {}
    for part in text.split(","):
        if ":" not in part:
            continue
        key, _, value = part.partition(":")
        key = key.strip()
        value = value.strip()
        if key and value:
            result[key] = value
    return result


def merge_params(info: dict[str, str], features: dict[str, str]) -> dict[str, str]:
    """InfoObject values override feature-text values when both present."""
    merged = dict(features)
    for key, value in info.items():
        if value:
            merged[key] = value
    return merged


def has_keyword(text: str | None, *keywords: str) -> bool:
    return bool(text) and any(kw in text for kw in keywords)


async def collect_listing_links(page: Page, max_pages: int | None = None) -> list[str]:
    """Paginate through search results, return all detail-page URLs.

    max_pages caps the number of pages walked (None = until pagination runs out).
    Useful for smoke runs.
    """
    links: list[str] = []
    pages_seen = 0

    while True:
        for anchor in await page.query_selector_all("a.with_hash2"):
            href = await anchor.get_attribute("href")
            if href:
                links.append(HOST + href)

        pages_seen += 1
        if max_pages is not None and pages_seen >= max_pages:
            break

        next_btn = await page.query_selector("a[rel=next]")
        if not next_btn:
            break

        await next_btn.click()
        await page.wait_for_selector("div.boxCatalog2", timeout=PAGE_TIMEOUT_MS)

    return list(dict.fromkeys(link.split("?")[0] for link in links))


_EXTRACT_PARAMS_JS = """
() => {
    const result = {};
    document.querySelectorAll('.nameInfoObject').forEach(el => {
        const strong = el.querySelector('strong');
        if (!strong) return;
        const label = strong.innerText.trim().replace(':', '');
        const value = el.innerText.replace(strong.innerText, '').trim();
        result[label] = value;
    });
    return result;
}
"""


async def extract_info_params(page: Page) -> dict[str, str]:
    return await page.evaluate(_EXTRACT_PARAMS_JS)


async def fetch_vin_by_click(page: Page) -> str:
    """Click the "show VIN" button and read the popup contents."""
    try:
        btn = await page.query_selector("button.hidden-vin")
        if not btn:
            return ""
        await btn.click()
        await page.wait_for_function(
            "() => { const el = document.querySelector('#cboxLoadedContent');"
            " return el && /[A-HJ-NPR-Z0-9]{17}/i.test(el.innerText); }",
            timeout=4000,
        )
        content = await page.evaluate(
            "() => document.querySelector('#cboxLoadedContent')?.innerText || ''"
        )
        await page.evaluate("() => { try { $.colorbox.close(); } catch(e) {} }")
        return content
    except Exception:
        return ""


async def fetch_vin_via_ajax(context: BrowserContext, car_id: str) -> str:
    """Fallback: hit the JSON endpoint autopapa uses internally."""
    vin_url = f"{HOST}/get_vin/ge/{car_id}"
    if not await robots.can_fetch(vin_url):
        return ""
    page = await context.new_page()
    try:
        await page.route("**/*", block_heavy_resources)
        await page.goto(vin_url, wait_until="domcontentloaded", timeout=10_000)
        return await page.content()
    except Exception:
        return ""
    finally:
        await page.close()


async def extract_contact(page: Page) -> tuple[str, str]:
    """Returns (location, seller_name). Seller is often empty (just a phone)."""
    raw = await page.evaluate(
        "() => document.querySelector('.contactObjectNew > div')?.innerText?.trim() || ''"
    )
    lines = [line.strip() for line in raw.split("\n") if line.strip()]

    location = re.split(r"\s*\|\s*", lines[0])[0].strip() if lines else ""

    seller = ""
    if len(lines) > 1:
        before_call = re.split(r",?\s*დარეკეთ", lines[1])[0].strip()
        seller = before_call.strip(",").strip()

    return location, seller


async def extract_meta(page: Page) -> tuple[int | None, str]:
    """Returns (views, posted_date)."""
    views: int | None = None
    posted = ""
    for item in await page.query_selector_all(".info-ads-page .item"):
        text = (await item.inner_text()).strip()
        if "ნახვა" in text:
            views = first_int(text)
        elif "განთავსებულია" in text:
            posted = text.replace("განთავსებულია:", "").strip()
    return views, posted


async def extract_video(page: Page) -> str:
    for el in await page.query_selector_all(".thumbs .video a"):
        href = await el.get_attribute("href")
        if href and not href.startswith(("#", "javascript:")):
            return href

    iframe = await page.query_selector("#mainVideo iframe")
    if iframe:
        src = await iframe.get_attribute("src")
        if src:
            return src
    return ""


async def extract_photos(page: Page) -> list[str]:
    photos: list[str] = []
    for el in await page.query_selector_all("a.hidden-galler-images"):
        href = await el.get_attribute("href")
        if href:
            photos.append(href)
    return photos


async def extract_prices(page: Page) -> tuple[int | None, str, int | None]:
    """Returns (price, currency, price_with_georgian_customs)."""
    price_el = await page.query_selector(".priceObject")
    price_raw = (await price_el.inner_text()).strip() if price_el else ""
    price_amount, price_currency = split_price(price_raw)

    pwc_el = await page.query_selector(
        ".country-prices__card--current .country-prices__value"
    )
    price_with_customs = (
        first_int((await pwc_el.inner_text()).strip()) if pwc_el else None
    )

    return price_amount, price_currency, price_with_customs


async def scrape_one(
    context: BrowserContext, url: str, semaphore: asyncio.Semaphore
) -> Car | None:
    async with semaphore:
        for attempt in range(RETRY_PER_CAR):
            page = await context.new_page()
            try:
                await page.route("**/*", block_heavy_resources)
                await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                await page.wait_for_selector(".titleObject", timeout=8_000)
                return await _build_car_from_page(context, page, url)
            except Exception as exc:
                if attempt == RETRY_PER_CAR - 1:
                    print(f"[FAIL] {url} — {exc}")
                    return None
                await asyncio.sleep(1)
            finally:
                await page.close()

        return None


async def _build_car_from_page(context: BrowserContext, page: Page, url: str) -> Car:
    car_id = extract_id(url)

    title = await page.evaluate(
        "() => document.querySelector('.titleObject')?.firstChild?.textContent?.trim() || ''"
    )
    title_parts = title.split()
    manufacturer = title_parts[0] if title_parts else ""
    model = " ".join(title_parts[1:]) if len(title_parts) > 1 else ""

    info_params = await extract_info_params(page)
    ca_el = await page.query_selector(".comment-all")
    features_text = (await ca_el.inner_text()).strip() if ca_el else ""
    params = merge_params(info_params, parse_features(features_text))

    price_amount, price_currency, price_with_customs = await extract_prices(page)

    phone_el = await page.query_selector('a[href^="tel:"]')
    phone = format_phone(await phone_el.get_attribute("href")) if phone_el else ""

    customs_el = await page.query_selector(".contactObjectNew nobr")
    customs_text = (await customs_el.inner_text()).strip() if customs_el else ""
    customs_cleared = parse_customs(customs_text)

    location, seller_name = await extract_contact(page)

    cs_el = await page.query_selector(".comment-seller")
    seller_text = (await cs_el.inner_text()).strip() if cs_el else ""
    description = clean_text(features_text + "\n\n" + seller_text)

    views, posted = await extract_meta(page)
    video_url = await extract_video(page)
    image_urls = await extract_photos(page)

    vin_from_click = await fetch_vin_by_click(page)
    vin_from_ajax = await fetch_vin_via_ajax(context, car_id) if car_id else ""
    vin = best_vin(vin_from_click, description, vin_from_ajax)

    mileage = first_int(params.get("გარბენი", "").split("/")[0])

    return Car(
        source=SOURCE,
        source_id=car_id,
        url=url,
        manufacturer=manufacturer,
        model=model,
        year=clean_int(params.get("გამოშვების წელი")),
        body_type=params.get("ძარის ტიპი", ""),
        price_amount=price_amount,
        price_currency=price_currency,
        price_with_customs=price_with_customs,
        engine_volume_l=clean_engine_volume(params.get("ძრავის მოცულობა")),
        engine_type=params.get("ძრავის ტიპი", ""),
        cylinders=sane_int(params.get("ცილინდრების რაოდენობა"), 1, 16),
        power_hp=sane_int(params.get("სიმძლავრე"), 1, 2000),
        has_turbo=has_keyword(features_text, "ტურბო"),
        gearbox=params.get("გადაცემათა კოლოფი", ""),
        drive_wheels=params.get("წამყვანი თვლები", ""),
        mileage_km=mileage,
        color=params.get("ძარის ფერი", ""),
        doors=first_int(params.get("კარები")),
        seats=first_int(params.get("ადგილების რაოდენობა")),
        interior_color=params.get("სალონის ფერი", ""),
        interior_material=params.get("მასალები", ""),
        steering=normalize_steering(features_text),
        condition=params.get("მდგომარეობა", ""),
        customs_cleared=customs_cleared,
        vin=vin,
        location=location,
        seller_name=seller_name,
        phone=phone,
        posted_date=posted,
        views=views,
        description=description,
        video_url=video_url,
        image_urls=image_urls,
    )


async def run(max_pages: int | None = None, refresh_all: bool = False) -> None:
    """Full parser.

    max_pages: cap on listing pagination (None = all). Smoke runs use 1.
    refresh_all: if True, re-scrape rows we already have (default skips them).
    """
    print(f"AutoPapa parser (concurrency={CONCURRENT_PAGES}, max_pages={max_pages})")

    if not await robots.can_fetch(START_URL):
        print(f"  robots.txt disallows {START_URL} — skipping")
        return

    already_saved = await get_existing_ids(SOURCE) if not refresh_all else set()
    print(f"  In DB: {len(already_saved)} listings")

    start_time = time.time()

    async with async_playwright() as playwright:
        browser, context = await create_stealth_context(playwright)
        try:
            page = await context.new_page()
            await page.route("**/*", block_heavy_resources)
            await page.goto(START_URL, wait_until="domcontentloaded")
            await page.wait_for_selector("div.boxCatalog2")
            all_links = await collect_listing_links(page, max_pages=max_pages)
            await page.close()

            new_links = [link for link in all_links if extract_id(link) not in already_saved]
            total, new = len(all_links), len(new_links)
            print(f"  Found: {total} | New: {new} | Skipping: {total - new}")

            if not new_links:
                print("Nothing new to scrape.")
                return

            await _scrape_all(context, new_links, start_time)
        finally:
            await context.close()
            await browser.close()

    print(f"\nDone in {time.time() - start_time:.0f}s")


async def _scrape_all(context: BrowserContext, urls: list[str], start_time: float) -> None:
    semaphore = asyncio.Semaphore(CONCURRENT_PAGES)
    tasks = [scrape_one(context, url, semaphore) for url in urls]

    buffer: list[Car] = []
    done = saved = 0
    total = len(urls)

    for coro in asyncio.as_completed(tasks):
        done += 1
        car = await coro

        if car is None:
            print(f"[{done}/{total}] FAIL")
            continue

        issues = validate_car(car)
        if issues:
            print(f"  [warn] {car.source_id}: {', '.join(issues[:3])}")

        buffer.append(car)

        if len(buffer) >= CONCURRENT_PAGES * 2:
            saved += await upsert_cars(buffer)
            append_cars_to_csv(buffer, SOURCE)
            buffer.clear()

        if done % 5 == 0 or done == total:
            elapsed = time.time() - start_time
            rate = done / elapsed if elapsed else 0
            eta_s = (total - done) / rate if rate else 0
            print(
                f"[{done}/{total}] saved:{saved} "
                f"rate:{rate:.1f}/s ETA:{eta_s:.0f}s "
                f"last:{car.manufacturer} {car.model}"
            )

    if buffer:
        saved += await upsert_cars(buffer)
        append_cars_to_csv(buffer, SOURCE)


if __name__ == "__main__":
    import sys

    from src.common.runtime import run as _run_async

    args = sys.argv[1:]
    refresh = "--refresh" in args
    args = [a for a in args if a != "--refresh"]
    if args and args[0] == "test" and len(args) > 1:
        _run_async(run(max_pages=int(args[1]), refresh_all=refresh))
    else:
        _run_async(run(refresh_all=refresh))
