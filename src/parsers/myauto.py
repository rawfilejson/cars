"""Scraper for myauto.ge listings.

We don't scrape the HTML — myauto.ge uses font obfuscation that scrambles
Georgian letters in the rendered DOM. Instead we hit api2.myauto.ge directly,
which returns clean JSON.

Cloudflare bot-fight on api2.myauto.ge blocks plain httpx requests, so we
warm up by visiting myauto.ge in Playwright first (to pick up clearance
cookies), then use the browser context's `request` to call the API.
"""

from __future__ import annotations

import asyncio
import time

from playwright.async_api import BrowserContext, async_playwright

from src.common.anti_detection import block_heavy_resources, create_stealth_context
from src.common.config import CONCURRENT_PAGES, PAGE_TIMEOUT_MS
from src.common.db import get_existing_ids, upsert_cars
from src.common.models import Car
from src.common.normalize import clean_text, format_phone
from src.common.vin import best_vin, find_vin


SOURCE = "myauto"
WEBSITE = "https://www.myauto.ge"
API_BASE = "https://api2.myauto.ge"
LIST_URL = f"{API_BASE}/ka/products"
CAR_URL_TEMPLATE = "https://www.myauto.ge/ka/pr/{car_id}/sale"
IMAGE_URL_TEMPLATE = "https://static.my.ge/myauto/photos/{photo}/large/{car_id}_{n}.jpg"

# Lookup tables for myauto enum IDs. These come from their /appdata
# endpoints but are stable enough to hard-code.
CURRENCY_MAP = {1: "USD", 2: "EUR", 3: "GEL"}

FUEL_MAP = {
    1: "ჰიბრიდი", 2: "ბენზინი", 3: "დიზელი", 4: "ელექტრო",
    5: "ბენზინი/გაზი", 6: "ჰიბრიდი", 7: "დატენვადი ჰიბრიდი",
}
GEARBOX_MAP = {1: "მექანიკა", 2: "ავტომატიკა", 3: "ტიპტრონიკი", 4: "ვარიატორი"}
DRIVE_MAP = {1: "წინა", 2: "უკანა", 3: "4x4"}
DOORS_MAP = {1: 3, 2: 5, 3: 6}                # mapped to integer door count
MATERIAL_MAP = {1: "ტყავი", 2: "ნაჭერი", 3: "ველვეტი", 4: "კომბინირებული", 5: "სხვა"}
COLOR_MAP = {
    1: "თეთრი", 2: "შავი", 3: "წითელი", 4: "მწვანე", 5: "ლურჯი",
    6: "ვერცხლისფერი", 7: "ყვითელი", 8: "ნარინჯისფერი", 9: "ყავისფერი",
    10: "ოქროსფერი", 11: "ბორდოსფერი", 12: "რუხი", 13: "შავი მეტალიკი",
    14: "რუხი მეტალიკი", 15: "მუქი ლურჯი", 16: "ვერცხლისფერი მეტალიკი",
    17: "ბეჟი", 18: "მწვანე მეტალიკი", 19: "სხვა",
}
LOCATION_MAP = {
    1: "საქართველო", 2: "თბილისი", 3: "ბათუმი", 4: "ქუთაისი", 5: "რუსთავი",
    6: "გორი", 7: "ფოთი", 8: "ზუგდიდი", 9: "ხაშური", 10: "სამტრედია",
    11: "სენაკი", 12: "ოზურგეთი", 13: "მცხეთა", 14: "ახალციხე", 15: "მარნეული",
    16: "თელავი", 17: "ბორჯომი", 18: "ქობულეთი", 19: "გარდაბანი", 20: "კასპი",
}
CATEGORY_MAP = {
    1: "სედანი", 2: "ჰეტჩბეკი", 3: "უნივერსალი", 4: "კუპე", 5: "ჯიპი",
    6: "პიკაპი", 7: "კაბრიოლეტი", 8: "მინივენი", 9: "მიკროავტობუსი",
    10: "ლიმუზინი", 11: "ფურგონი", 12: "სატვირთო", 66: "კროსოვერი",
}


# Feature flags returned in each car JSON, paired with display labels.
FEATURE_FLAGS = {
    "abs": "ABS",
    "esd": "ESP",
    "el_windows": "ელ. შუშები",
    "conditioner": "კონდინციონერი",
    "climat_control": "კლიმატკონტროლი",
    "leather": "ტყავის სალონი",
    "disks": "ალუმინის დისკები",
    "nav_system": "ნავიგაცია",
    "central_lock": "ცენტრალური საკეტი",
    "hatch": "ლუქი",
    "alarm": "სიგნალიზაცია",
    "board_comp": "ბორტკომპიუტერი",
    "hydraulics": "ჰიდრო",
    "chair_warming": "სავარძლების გათბობა",
    "obstacle_indicator": "პარკტრონიკი",
    "back_camera": "უკანა კამერა",
    "start_stop": "Start/Stop",
    "has_turbo": "ტურბო",
    "tech_inspection": "ტექდათვალიერება",
}


def _to_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _engine_volume_to_liters(cc: int | None) -> float | None:
    if cc is None or cc <= 0:
        return None
    return round(cc / 1000, 2)


def _build_image_urls(item: dict, max_images: int = 20) -> list[str]:
    car_id = item.get("car_id")
    photo = item.get("photo")
    pic_count = _to_int(item.get("pic_number")) or 0
    if not (car_id and photo and pic_count):
        return []

    photo_ver = item.get("photo_ver") or ""
    urls: list[str] = []
    for i in range(1, min(pic_count, max_images) + 1):
        url = IMAGE_URL_TEMPLATE.format(photo=photo, car_id=car_id, n=i)
        if photo_ver:
            url += f"?v={photo_ver}"
        urls.append(url)
    return urls


def _build_description(item: dict) -> str:
    parts: list[str] = []

    raw = clean_text(item.get("car_desc") or "")
    if raw:
        parts.append(raw)

    flags = [label for key, label in FEATURE_FLAGS.items() if item.get(key)]
    if flags:
        parts.append("ფიჩერები: " + ", ".join(flags))

    if item.get("airbags"):
        parts.append(f"აირბაგები: {item['airbags']}")

    return "\n\n".join(parts)


def _build_phone(item: dict) -> str:
    """The listings endpoint returns the phone masked ("995557607***").

    Storing the masked version with a + prefix would create useless matches
    on phone search. Treat any phone containing `*` as missing — the reveal
    endpoint is a separate per-car request (TODO if we ever need full phones).
    """
    raw = item.get("client_phone")
    if raw is None:
        return ""
    raw_str = str(raw)
    if "*" in raw_str:
        return ""
    return format_phone(raw_str)


def _build_vin(item: dict) -> str:
    """VIN can be in `vin` field (possibly masked with *) or buried in description."""
    raw = (item.get("vin") or "").strip()
    if raw and "*" not in raw:
        return raw.upper()

    # Try description text
    in_desc = find_vin(item.get("car_desc") or "")
    if in_desc:
        return in_desc

    # Return the masked version if that's all we have
    return raw.upper()


def _build_model(item: dict) -> str:
    """Combine `model_name` and `car_model` if both present and not redundant."""
    name = (item.get("model_name") or "").strip()
    extra = (item.get("car_model") or "").strip()
    if not extra:
        return name
    if extra.lower() in name.lower():
        return name
    return f"{name} {extra}".strip()


def item_to_car(item: dict) -> Car | None:
    car_id = item.get("car_id")
    if not car_id:
        return None

    return Car(
        source=SOURCE,
        source_id=str(car_id),
        url=CAR_URL_TEMPLATE.format(car_id=car_id),
        manufacturer=(item.get("man_name") or "").strip(),
        model=_build_model(item),
        year=_to_int(item.get("prod_year")),
        body_type=CATEGORY_MAP.get(item.get("category_id"), ""),
        price_amount=_to_int(item.get("price")),
        price_currency=CURRENCY_MAP.get(item.get("currency_id"), ""),
        engine_volume_l=_engine_volume_to_liters(_to_int(item.get("engine_volume"))),
        engine_type=FUEL_MAP.get(item.get("fuel_type_id"), ""),
        cylinders=_to_int(item.get("cylinders")),
        power_hp=_to_int(item.get("hp")),
        has_turbo=bool(item.get("has_turbo")),
        gearbox=GEARBOX_MAP.get(item.get("gear_type_id"), ""),
        drive_wheels=DRIVE_MAP.get(item.get("drive_type_id"), ""),
        mileage_km=_to_int(item.get("car_run_km") or item.get("car_run")),
        color=COLOR_MAP.get(item.get("color_id"), ""),
        doors=DOORS_MAP.get(item.get("door_type_id")),
        interior_color=COLOR_MAP.get(item.get("saloon_color_id"), ""),
        interior_material=MATERIAL_MAP.get(item.get("saloon_material_id"), ""),
        steering="მარჯვენა" if item.get("right_wheel") else "მარცხენა",
        customs_cleared=bool(item.get("customs_passed")),
        has_catalyst=True if item.get("has_catalyst") == 1 else (
            False if item.get("has_catalyst") == 2 else None
        ),
        tech_inspection=bool(item.get("tech_inspection")) if item.get("tech_inspection") is not None else None,
        vin=_build_vin(item),
        license_plate=(item.get("license_number") or "").strip(),
        location=LOCATION_MAP.get(item.get("location_id"), ""),
        seller_name=(item.get("client_name") or "").strip(),
        phone=_build_phone(item),
        posted_date=(item.get("order_date") or "").strip(),
        views=_to_int(item.get("views")),
        description=_build_description(item),
        video_url=(item.get("video_url") or "").strip(),
        image_urls=_build_image_urls(item),
    )


# myauto's official app/web sends this exact User-Agent. The CLDB tag is what
# their backend whitelists past Cloudflare's bot-fight on api2.myauto.ge.
MYAUTO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) CLDB 2.1.3.08; Chrome/129.0.0.0; Safari/537.36"
)


async def _api_get(context: BrowserContext, path: str, params: dict | None = None) -> dict | None:
    url = f"{API_BASE}{path}"
    headers = {
        "Accept": "*/*",
        "Accept-Language": "ka",
        "Origin": "https://myauto.ge",
        "Referer": "https://myauto.ge/",
        "User-Agent": MYAUTO_UA,
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
    }
    try:
        response = await context.request.get(url, params=params or {}, headers=headers)
        if not response.ok:
            return None
        return await response.json()
    except Exception as exc:
        print(f"  API error {url}: {exc}")
        return None


async def warmup(context: BrowserContext) -> None:
    """Visit myauto.ge so Playwright solves any Cloudflare JS challenge."""
    page = await context.new_page()
    try:
        await page.route("**/*", block_heavy_resources)
        await page.goto(WEBSITE, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        await asyncio.sleep(3)
    finally:
        await page.close()


async def fetch_page(context: BrowserContext, page_num: int) -> dict | None:
    return await _api_get(context, "/ka/products", {
        "TypeID": 0,
        "ForRent": "false",
        "CurrencyID": 3,            # GEL — we'll keep all prices in source currency
        "MileageType": 1,
        "Page": page_num,
    })


async def run() -> None:
    print(f"MyAuto parser (concurrency={CONCURRENT_PAGES})")

    already_saved = await get_existing_ids(SOURCE)
    print(f"  In DB: {len(already_saved)} listings")

    start_time = time.time()

    async with async_playwright() as playwright:
        browser, context = await create_stealth_context(playwright)
        try:
            print("  Warming up (visiting myauto.ge)...")
            await warmup(context)

            print("  Fetching page 1 for total count...")
            first_response = await fetch_page(context, 1)

            if not first_response or first_response.get("statusCode") != 1:
                print("  Failed to reach the API. Got:", first_response)
                return

            meta = (first_response.get("data") or {}).get("meta") or {}
            total = meta.get("total", 0)
            last_page = meta.get("last_page", 0)
            print(f"  Total: {total} listings across {last_page} pages")

            new_cars = 0
            for page_num in range(1, last_page + 1):
                data = first_response if page_num == 1 else await fetch_page(context, page_num)

                if not data or data.get("statusCode") != 1:
                    print(f"  [page {page_num}] failed, skipping")
                    continue

                items = (data.get("data") or {}).get("items") or []
                batch: list[Car] = []
                for item in items:
                    if str(item.get("car_id")) in already_saved:
                        continue
                    try:
                        car = item_to_car(item)
                    except Exception as exc:
                        print(f"  [parse error] car_id={item.get('car_id')}: {exc}")
                        continue
                    if car:
                        batch.append(car)

                if batch:
                    saved = await upsert_cars(batch)
                    new_cars += saved
                    for car in batch:
                        already_saved.add(car.source_id)

                if page_num % 10 == 0 or page_num == last_page:
                    elapsed = time.time() - start_time
                    rate = page_num / elapsed if elapsed else 0
                    print(
                        f"  [{page_num}/{last_page}] new:{new_cars} "
                        f"rate:{rate:.1f} pages/s"
                    )

            print(f"\nDone. Added {new_cars} new listings in {time.time() - start_time:.0f}s")
        finally:
            await context.close()
            await browser.close()


if __name__ == "__main__":
    from src.common.runtime import run as _run_async

    _run_async(run())
