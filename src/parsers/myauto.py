"""myauto.ge-ის parser — HTML scrape Playwright-ით.

ძველი API-based ვერსია გადავიყვანეთ HTML-ზე რომ:
  * არ ვმოქმედებდეთ ფარულ API endpoint-ზე (myauto-მ შეცვალოს — ჩვენ ჩავარდებით)
  * ნამდვილი user-ის ნახულობას ვაჯერებდეთ — visible HTML იგივეა რასაც მომხმარებელი ხედავს
  * ერთიდაიგივე pattern გვქონდეს autopapa-სთან — სამომავლოდ ერთად მოვლა გვინდა

ნაკადი:
  1. listing pages (TODO Task #9) → მანქანების URL-ების სია
  2. ყოველი URL → scrape_one() → Car
  3. batch upsert DB-ში + CSV append (TODO Task #8)

ფონტ-obfuscation აღარ არსებობს (იყო თუ არა — დღეს არ ჩანს). სუფთა HTML ემთხვევა
რენდერდ ეკრანს.
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
    parse_bool_yes_no,
)
from src.common.vin import find_vin, is_valid_vin


SOURCE = "myauto"
HOST = "https://www.myauto.ge"
DETAIL_URL_TEMPLATE = "https://www.myauto.ge/ka/pr/{car_id}/sale"

_ID_FROM_URL_RE = re.compile(r"/pr/(\d+)(?:/|$)")


def extract_id(url: str) -> str:
    """URL-დან car_id. `.../pr/120183626/sale` → `"120183626"`."""
    match = _ID_FROM_URL_RE.search(url)
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# სპეც-ცხრილის labels — ქართულიდან Car მოდელის ფილდამდე
# ---------------------------------------------------------------------------

# label → handler. handler იღებს raw string-ს, აბრუნებს იმას რაც Car-ში ჩაჯდება.
# რომელ ფილდში — ცალკე SPEC_TO_FIELD რუკაში.

SPEC_TO_FIELD = {
    "მწარმოებელი":          "manufacturer",
    "მოდელი":               "model",
    "წელი":                 "year",
    "კატეგორია":            "body_type",
    "გარბენი":              "mileage_km",
    "საწვავის ტიპი":        "engine_type",
    "ძრავის მოცულობა":      "engine_volume_l",
    "ცილინდრები":           "cylinders",
    "გადაცემათა კოლოფი":    "gearbox",
    "წამყვანი თვლები":      "drive_wheels",
    "კარები":               "doors",
    "საჭე":                 "steering",
    "ფერი":                 "color",
    "სალონის ფერი":         "interior_color",
    "სალონის მასალა":       "interior_material",
    "ტექ. დათვალიერება":    "tech_inspection",
    "კატალიზატორი":         "has_catalyst",
    "მდგომარეობა":          "condition",
    "ადგილების რაოდენობა":  "seats",
    "სიმძლავრე":            "power_hp",
}

# რომელი ფილდები int უნდა იყოს (ძრავის გარდა)
_INT_FIELDS = {"year", "mileage_km", "cylinders", "doors", "seats", "power_hp"}
_BOOL_FIELDS = {"tech_inspection", "has_catalyst"}


def _convert_spec_value(field: str, raw: str) -> object:
    """Raw სტრინგი → Car-ის field-ის შესაბამისი ტიპი."""
    if field == "engine_volume_l":
        return clean_engine_volume(raw)
    if field == "doors":
        # "4/5" → 4
        return clean_int(raw.split("/")[0]) if raw else None
    if field in _INT_FIELDS:
        return clean_int(raw)
    if field in _BOOL_FIELDS:
        return parse_bool_yes_no(raw)
    if field == "steering":
        if "მარცხ" in raw:
            return "მარცხენა"
        if "მარჯვ" in raw:
            return "მარჯვენა"
        return ""
    return raw.strip()


# ---------------------------------------------------------------------------
# გვერდიდან მონაცემების ამოღება
# ---------------------------------------------------------------------------

# `div[class*="py-[4px]"]` — ცხრილის ერთი ხაზი. ორი child div: label, value.
_EXTRACT_SPEC_JS = """
() => {
    const result = {};
    document.querySelectorAll('div[class*="py-[4px]"]').forEach(row => {
        const kids = row.querySelectorAll(':scope > div');
        if (kids.length !== 2) return;
        const label = kids[0].innerText.trim();
        const value = kids[1].innerText.trim();
        if (label && value && !label.includes('\\n')) {
            result[label] = value;
        }
    });
    return result;
}
"""


async def extract_spec_params(page: Page) -> dict[str, str]:
    return await page.evaluate(_EXTRACT_SPEC_JS)


# ფიჩერების სია — svg-ში `<g id="done">` ნიშნავს რომ ფიჩერი არსებობს.
# `id="remove"` — არ არსებობს. ვიღებთ მხოლოდ "done"-ებს.
_EXTRACT_FEATURES_JS = """
() => {
    const features = [];
    document.querySelectorAll('div.flex.items-center[class*="my-[12px]"]').forEach(row => {
        const g = row.querySelector('svg g[id]');
        if (!g || g.id !== 'done') return;
        const text = row.innerText.trim();
        if (text) features.push(text);
    });
    return features;
}
"""


async def extract_features(page: Page) -> list[str]:
    return await page.evaluate(_EXTRACT_FEATURES_JS)


# title: "2014 Lexus ES 350 Base" — წელი, მწარმოებელი, მოდელი
_TITLE_RE = re.compile(r"^(\d{4})\s+(\S+)\s+(.*)$")


async def extract_title(page: Page) -> tuple[int | None, str, str]:
    """Title-ი ფორმატის "2014 Lexus ES 350 Base" → (year, manufacturer, model)."""
    el = await page.query_selector('p.leading-\\[100\\%\\]')
    if not el:
        el = await page.query_selector("h1")
    if not el:
        return None, "", ""

    text = (await el.inner_text()).strip()
    match = _TITLE_RE.match(text)
    if not match:
        return None, "", text

    year = int(match.group(1))
    manufacturer = match.group(2)
    model = match.group(3).strip()
    return year, manufacturer, model


async def extract_description(page: Page) -> str:
    """აღწერა — `p.text-raisin-80.whitespace-pre-wrap`."""
    el = await page.query_selector('p[class*="text-raisin-80"][class*="whitespace-pre-wrap"]')
    if not el:
        return ""
    return clean_text(await el.inner_text())


async def extract_photos(page: Page) -> list[str]:
    """ფოტოები — `/large/` ვერსიები. Thumbs-ი → large-ად გადავაქცევთ."""
    photos: list[str] = []
    seen: set[str] = set()
    elements = await page.query_selector_all("img[src*='/photos/']")
    for el in elements:
        src = await el.get_attribute("src")
        if not src:
            continue
        # thumbs URL-ი იგივეა large-სთან, მხოლოდ path-ში /thumbs/ vs /large/
        large = src.replace("/thumbs/", "/large/")
        key = large.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        photos.append(large)
    return photos


# myauto-ს URL pattern: /photos/{path}/{size}/{car_id}_{n}.jpg
_PHOTO_N_RE = re.compile(r"/large/(\d+)_(\d+)\.jpg")


def _ensure_all_photos(photos: list[str], car_id: str, max_photos: int = 40) -> list[str]:
    """თუ HTML-ში მხოლოდ thumbs ჩანდა (გვერდმა lazy load გვერდით), მაინც
    ვაშენებთ ყველა _1.jpg, _2.jpg, ... _N.jpg URL-ს რომელიც ხელმისაწვდომი იყო.

    გავიგებთ პატერნს პირველი URL-დან, შემდეგ ვამატებთ მისი ვარიანტებს.
    """
    if not photos:
        return []

    first = photos[0]
    match = _PHOTO_N_RE.search(first)
    if not match:
        return photos

    base = first.split("_")[0]                           # ...{car_id} part
    base_id = match.group(1)
    if base_id != car_id:
        # თუ ID-ი არ ემთხვევა, არ ჩავერევთ
        return photos

    # მაქს რა n-ი ვნახეთ
    max_n = 1
    for p in photos:
        m = _PHOTO_N_RE.search(p)
        if m:
            max_n = max(max_n, int(m.group(2)))

    suffix = first[first.find(".jpg"):]                  # `.jpg?v=11` ან `.jpg`

    return [f"{base}_{n}{suffix}" for n in range(1, min(max_n, max_photos) + 1)]


# myauto-ს გვერდზე ფასს არ აქვს valuta-ის სიმბოლო ტექსტში — სიმბოლო ცალკე
# SVG button-ებშია. ვცდილობთ:
#   1. პირველი p.font-bold რომელშიც მხოლოდ ციფრებია = ფასი
#   2. იქვე parent-ში არსებული active "rounded-full" ღილაკი = ვალუტა
#      active = class-ში არ არის "/20" (inactive ღილაკები /20 opacity-ით)
#      ვალუტა SVG path-ის data-name (`$`/`€`/`₾`) ან id-ში (USD/EUR/GEL)
_PRICE_AND_CURRENCY_JS = """
() => {
    const price_p = Array.from(document.querySelectorAll('p.font-bold')).find(el => {
        const t = (el.innerText || '').trim();
        return /^[\\d,. ]+$/.test(t) && t.length >= 3;
    });
    if (!price_p) return null;

    let currency = '';
    const parent = price_p.parentElement;
    const spans = parent?.querySelectorAll('span[class*="rounded-full"]') || [];
    for (const s of spans) {
        const cls = (s.className || '').toString();
        if (cls.includes('/20')) continue;                  // inactive ღილაკი
        const path = s.querySelector('svg path[id], svg path[data-name]');
        const id = path?.getAttribute('id') || '';
        const dn = path?.getAttribute('data-name') || '';
        if (id === 'USD' || id === 'EUR' || id === 'GEL') {
            currency = id;
        } else if (dn === '$') currency = 'USD';
        else if (dn === '€') currency = 'EUR';
        else if (dn === '₾') currency = 'GEL';
        break;
    }

    return { price_text: price_p.innerText.trim(), currency: currency };
}
"""


async def extract_price(page: Page) -> tuple[int | None, str]:
    """ფასი + ვალუტა (active currency switcher ღილაკიდან)."""
    result = await page.evaluate(_PRICE_AND_CURRENCY_JS)
    if not result:
        return None, ""

    amount = clean_int(result["price_text"])
    return amount, result["currency"]


# VIN — სელერმა შეიყვანა თუ არა?
_NO_VIN_MARKER = "გამყიდველს არ აქვს VIN კოდი"


async def extract_vin(page: Page, description: str) -> str:
    """VIN ფილდიდან, თუ არსებობს. სხვაგვარად description-ში ვეძებთ."""
    body_text = await page.evaluate("() => document.body.innerText")

    if _NO_VIN_MARKER in body_text:
        # სელერმა საერთოდ არ შეიყვანა — შესაძლოა description-ში მაინც წერია
        return find_vin(description)

    # ვცადოთ შევხედოთ VIN-ად მსგავსი string-ი მთლიან გვერდზე
    vin_from_page = find_vin(body_text)
    if vin_from_page:
        return vin_from_page

    return find_vin(description)


# ტელეფონის ფილდი — IMPORTANT LIMITATION:
#
#   myauto გვერდს default-ად აქვს masked ნომერი ("599 51 5* **").
#   "ნომრის ნახვა" ღილაკზე click-ის შემდეგაც modal-ი ცარიელ მომხმარებლისთვის
#   მაინც ბრუნდება masked-ი href-ით: "tel:+995599515***" (ბოლო 3 ციფრი ფარული).
#
#   სრული ნომრის სანახავად საჭიროა JWT auth (login). ჩვენ ეს ჯერ არ გვაქვს.
#   ამიტომ ყველა myauto phone → ცარიელი string. გამყიდველს მაინც დაუკავშირდება
#   მომხმარებელი source URL-ით.

_MASK_CHARS = "*"


async def extract_phone(page: Page) -> str:
    """myauto-ს phone reveal — auth-ის გარეშე ფარულია, ვაბრუნებთ ცარიელს.

    თუ რომელიმე გვერდმა მაინც გვერდს გვაჩვენოს სრული ნომერი (test, future feature, ან
    cached state), ვაბრუნებთ format_phone-ით. სხვა შემთხვევაში "".
    """
    # ვცადოთ თუ უკვე visible-ია სრულად
    link = await page.query_selector('a[data-testid^="show-number-modal-phone"]')
    if not link:
        # არც button click შეჭამდა, რადგან modal იგივე masked link-ს ბრუნდება auth-ის გარეშე
        # უბრალოდ ვცადოთ რომ შემოწმდეს გვერდს არსებობს თუ არა უკვე ცარიელი ნომერი
        link = await page.query_selector('a[href^="tel:+995"]:not([href*="32 280"])')

    if not link:
        return ""

    href = await link.get_attribute("href") or ""
    if _MASK_CHARS in href:
        return ""
    return format_phone(href)


async def extract_seller_name(page: Page) -> str:
    """პროდავცის სახელი — როცა ჩანს."""
    # სავარაუდო selector-ები (HTML-ი ბოლომდე არ ვნახე — ვცდი ფართო ვერსიას)
    for selector in (
        '[data-testid="seller-name"]',
        'div[class*="seller-name"]',
        'p[class*="seller"]',
    ):
        el = await page.query_selector(selector)
        if el:
            text = (await el.inner_text()).strip()
            if text:
                return text
    return ""


async def extract_location(spec: dict) -> str:
    """location ჯერჯერობით სპეცში არ ჩანდა Lexus-ის გვერდზე. სხვა გვერდებზე
    შესაძლოა იყოს. ფოლბექი ცარიელია."""
    for key in ("ადგილმდებარეობა", "ლოკაცია", "მდებარეობა", "ქალაქი"):
        if key in spec:
            return spec[key]
    return ""


# ---------------------------------------------------------------------------
# ერთი მანქანის სრული scrape
# ---------------------------------------------------------------------------


async def scrape_one(
    context: BrowserContext,
    url: str,
    semaphore: asyncio.Semaphore | None = None,
) -> Car | None:
    """ერთი detail page-ი → Car. retry-ით.

    semaphore არასავალდებულოა — manual smoke test-ისთვის None გადააცი.
    """
    if semaphore is None:
        semaphore = asyncio.Semaphore(1)

    async with semaphore:
        for attempt in range(RETRY_PER_CAR):
            page = await context.new_page()
            try:
                await page.route("**/*", block_heavy_resources)
                await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                # ვუცადოთ რომ React component-ი ჩაიტვირთოს
                await page.wait_for_selector('div[class*="py-[4px]"]', timeout=8_000)
                return await _build_car_from_page(page, url)
            except Exception as exc:
                if attempt == RETRY_PER_CAR - 1:
                    print(f"[FAIL] {url} — {exc}")
                    return None
                await asyncio.sleep(1)
            finally:
                await page.close()

        return None


async def _build_car_from_page(page: Page, url: str) -> Car:
    car_id = extract_id(url)

    year_t, manuf_t, model_t = await extract_title(page)
    spec = await extract_spec_params(page)
    features = await extract_features(page)
    description = await extract_description(page)
    raw_photos = await extract_photos(page)
    photos = _ensure_all_photos(raw_photos, car_id)
    price_amount, price_currency = await extract_price(page)
    phone = await extract_phone(page)
    seller_name = await extract_seller_name(page)
    location = await extract_location(spec)
    vin = await extract_vin(page, description)
    if vin and not is_valid_vin(vin):
        # find_vin-ი უკვე ფილტრავს, მაგრამ რომ უცეცხლო ნაგვი არ შემოგვერივა
        vin = ""

    # სპეც-ცხრილიდან ფილდები
    spec_fields: dict[str, object] = {}
    for label, raw_value in spec.items():
        field = SPEC_TO_FIELD.get(label)
        if not field:
            continue
        spec_fields[field] = _convert_spec_value(field, raw_value)

    # title-დან მონაცემები (თუ spec-ში არ იყო, fallback)
    manufacturer = spec_fields.get("manufacturer") or manuf_t or ""
    model = spec_fields.get("model") or model_t or ""
    year = spec_fields.get("year") or year_t

    # ფიჩერების ტექსტური ვერსია description-ის ბოლოს
    desc_parts = [description] if description else []
    if features:
        desc_parts.append("ფიჩერები: " + ", ".join(features))
    full_description = "\n\n".join(desc_parts)

    return Car(
        source=SOURCE,
        source_id=car_id,
        url=url,
        manufacturer=str(manufacturer),
        model=str(model),
        year=year if isinstance(year, int) else None,
        body_type=str(spec_fields.get("body_type") or ""),
        price_amount=price_amount,
        price_currency=price_currency,
        engine_volume_l=spec_fields.get("engine_volume_l"),
        engine_type=str(spec_fields.get("engine_type") or ""),
        cylinders=spec_fields.get("cylinders"),
        power_hp=spec_fields.get("power_hp"),
        has_turbo=any("ტურბო" in f.lower() for f in features) or None,
        gearbox=str(spec_fields.get("gearbox") or ""),
        drive_wheels=str(spec_fields.get("drive_wheels") or ""),
        mileage_km=spec_fields.get("mileage_km"),
        color=str(spec_fields.get("color") or ""),
        doors=spec_fields.get("doors"),
        seats=spec_fields.get("seats"),
        interior_color=str(spec_fields.get("interior_color") or ""),
        interior_material=str(spec_fields.get("interior_material") or ""),
        steering=str(spec_fields.get("steering") or ""),
        condition=str(spec_fields.get("condition") or ""),
        tech_inspection=spec_fields.get("tech_inspection"),
        has_catalyst=spec_fields.get("has_catalyst"),
        vin=vin,
        location=location,
        seller_name=seller_name,
        phone=phone,
        description=full_description,
        image_urls=photos,
    )


# ---------------------------------------------------------------------------
# car_id-ების სიის ამოღება — Hybrid მიდგომა
#
# myauto-ს listings გვერდი React SPA-ია, pagination URL-ით არ მუშაობს.
# detail page-ებს HTML-ით ვიღებთ (სუფთა, რენდერდი data), მაგრამ car_id-ების
# ლისტი მხოლოდ XHR/API-დან მიდის. ამიტომ ერთადერთი API call ჩვენ ვუშვებთ
# api2.myauto.ge-ის products endpoint-ზე — გვაძლევს car_id-ების სიას.
# ---------------------------------------------------------------------------

API_BASE = "https://api2.myauto.ge"

# myauto-ს app-ი ამ User-Agent-ით უტევს ბექს — CLDB tag whitelist-ში
MYAUTO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) CLDB 2.1.3.08; Chrome/129.0.0.0; Safari/537.36"
)


async def _warmup(context: BrowserContext) -> None:
    """myauto.ge-ს ვხსნით, Cloudflare cookies-ი მოვიდეს."""
    page = await context.new_page()
    try:
        await page.route("**/*", block_heavy_resources)
        await page.goto(HOST, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        await asyncio.sleep(2)
    finally:
        await page.close()


async def _fetch_ids_page(context: BrowserContext, page_num: int) -> tuple[list[str], int]:
    """Returns (car_ids, last_page). მხოლოდ car_id ვიღებთ, სხვა ფილდები არ გვჭირდება."""
    headers = {
        "Accept": "*/*",
        "Accept-Language": "ka",
        "Origin": "https://myauto.ge",
        "Referer": "https://myauto.ge/",
        "User-Agent": MYAUTO_UA,
    }
    params = {
        "TypeID": 0,
        "ForRent": "false",
        "CurrencyID": 3,
        "MileageType": 1,
        "Page": page_num,
    }
    try:
        response = await context.request.get(
            f"{API_BASE}/ka/products", params=params, headers=headers
        )
        if not response.ok:
            return [], 0
        data = await response.json()
    except Exception as exc:
        print(f"  API page {page_num} error: {exc}")
        return [], 0

    if data.get("statusCode") != 1:
        return [], 0

    payload = data.get("data") or {}
    items = payload.get("items") or []
    ids = [str(item["car_id"]) for item in items if item.get("car_id")]
    last_page = (payload.get("meta") or {}).get("last_page", 0)
    return ids, last_page


async def collect_all_ids(
    context: BrowserContext, max_pages: int | None = None
) -> list[str]:
    """ყველა გვერდი → car_id-ების სრული სია (dedup-ით)."""
    print("  Warming up (visiting myauto.ge for CF cookies)...")
    await _warmup(context)

    print("  Fetching page 1 for total count...")
    first_ids, last_page = await _fetch_ids_page(context, 1)
    if not last_page:
        print("  Failed to reach API — got 0 pages")
        return []

    if max_pages:
        last_page = min(last_page, max_pages)
    print(f"  Total: ~{last_page * 30} listings across {last_page} pages")

    all_ids: list[str] = list(first_ids)
    seen: set[str] = set(first_ids)

    for page_num in range(2, last_page + 1):
        ids, _ = await _fetch_ids_page(context, page_num)
        for car_id in ids:
            if car_id in seen:
                continue
            seen.add(car_id)
            all_ids.append(car_id)
        if page_num % 50 == 0:
            print(f"  [API {page_num}/{last_page}] collected:{len(all_ids)}")

    return all_ids


# ---------------------------------------------------------------------------
# run() — სრული nakadi: API → IDs → HTML scrape → DB + CSV
# ---------------------------------------------------------------------------


async def run(max_pages: int | None = None) -> None:
    """პარსერი მთლიანად — API-ით ID-ები, HTML-ით detail-ები.

    max_pages=None → ყველა გვერდი. ცდისთვის: max_pages=2 → ~60 მანქანა.
    """
    print(f"MyAuto parser (HTML scrape mode, concurrency={CONCURRENT_PAGES})")

    already_saved = await get_existing_ids(SOURCE)
    print(f"  In DB: {len(already_saved)} listings")

    start_time = time.time()

    async with async_playwright() as playwright:
        browser, context = await create_stealth_context(playwright)
        try:
            all_ids = await collect_all_ids(context, max_pages=max_pages)
            new_ids = [cid for cid in all_ids if cid not in already_saved]
            print(f"  Found: {len(all_ids)} | New: {len(new_ids)} | "
                  f"Skipping: {len(all_ids) - len(new_ids)}")
            if not new_ids:
                print("Nothing new to scrape.")
                return

            urls = [DETAIL_URL_TEMPLATE.format(car_id=cid) for cid in new_ids]
            await _scrape_all(context, urls, start_time)
        finally:
            await context.close()
            await browser.close()

    print(f"\nDone in {time.time() - start_time:.0f}s")


async def _scrape_all(
    context: BrowserContext, urls: list[str], start_time: float
) -> None:
    semaphore = asyncio.Semaphore(CONCURRENT_PAGES)
    tasks = [scrape_one(context, url, semaphore) for url in urls]

    buffer: list[Car] = []
    done = saved = 0
    total = len(urls)

    for coro in asyncio.as_completed(tasks):
        done += 1
        car = await coro

        if car is None:
            continue

        buffer.append(car)

        if len(buffer) >= CONCURRENT_PAGES * 2:
            saved += await upsert_cars(buffer)
            append_cars_to_csv(buffer, SOURCE)
            buffer.clear()

        if done % 10 == 0 or done == total:
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


async def smoke_test(url: str) -> Car | None:
    """ერთი URL-ის სრული გავლა — debug-ისთვის.

    Usage:
        uv run python -c "from src.common.runtime import run as r; \\
            from src.parsers.myauto import smoke_test; \\
            r(smoke_test('https://www.myauto.ge/ka/pr/120183626/sale'))"
    """
    async with async_playwright() as playwright:
        browser, context = await create_stealth_context(playwright)
        try:
            car = await scrape_one(context, url)
            if car:
                print("=" * 60)
                print(f"car_id:       {car.source_id}")
                print(f"title:        {car.year} {car.manufacturer} {car.model}")
                print(f"price:        {car.price_amount} {car.price_currency}")
                print(f"mileage:      {car.mileage_km} km")
                print(f"engine:       {car.engine_volume_l} L, {car.engine_type}")
                print(f"gearbox:      {car.gearbox}")
                print(f"drive:        {car.drive_wheels}")
                print(f"color:        {car.color} (interior: {car.interior_color})")
                print(f"steering:     {car.steering}")
                print(f"VIN:          {car.vin or '(none)'}")
                print(f"phone:        {car.phone or '(masked)'}")
                print(f"photos:       {len(car.image_urls)}")
                print(f"description:  {car.description[:120]}...")
                print("=" * 60)
            else:
                print("FAILED")
            return car
        finally:
            await context.close()
            await browser.close()


if __name__ == "__main__":
    import sys

    from src.common.runtime import run as _run_async

    args = sys.argv[1:]

    if args and args[0] == "smoke":
        target_url = args[1] if len(args) > 1 else \
            "https://www.myauto.ge/ka/pr/120183626/sale"
        _run_async(smoke_test(target_url))
    elif args and args[0] == "test" and len(args) > 1:
        # ცდის run — შეზღუდული გვერდების რაოდენობით
        _run_async(run(max_pages=int(args[1])))
    else:
        _run_async(run())
