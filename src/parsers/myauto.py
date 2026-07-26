# parser for myauto.ge, scraping the HTML with playwright

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

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
    phone_from_text,
    sane_int,
)
from src.common.validators import validate_car
from src.common.vin import find_vin, is_valid_vin


SOURCE = "myauto"
HOST = "https://www.myauto.ge"
DETAIL_URL_TEMPLATE = "https://www.myauto.ge/ka/pr/{car_id}/sale"
IMAGE_URL_TEMPLATE = "https://static.my.ge/myauto/photos/{photo}/large/{car_id}_{n}.jpg"

_ID_FROM_URL_RE = re.compile(r"/pr/(\d+)(?:/|$)")


def extract_id(url: str) -> str:
    # car_id from the url
    match = _ID_FROM_URL_RE.search(url)
    return match.group(1) if match else ""


CURRENCY_MAP = {1: "USD", 2: "EUR", 3: "GEL"}
FUEL_MAP = {
    1: "ჰიბრიდი",
    2: "ბენზინი",
    3: "დიზელი",
    4: "ელექტრო",
    5: "ბენზინი/გაზი",
    6: "ჰიბრიდი",
    7: "დატენვადი ჰიბრიდი",
}
GEARBOX_MAP = {1: "მექანიკა", 2: "ავტომატიკა", 3: "ტიპტრონიკი", 4: "ვარიატორი"}
DRIVE_MAP = {1: "წინა", 2: "უკანა", 3: "4x4"}
DOORS_MAP = {1: 3, 2: 5, 3: 6}
MATERIAL_MAP = {1: "ტყავი", 2: "ნაჭერი", 3: "ველვეტი", 4: "კომბინირებული", 5: "სხვა"}
COLOR_MAP = {
    1: "თეთრი",
    2: "შავი",
    3: "წითელი",
    4: "მწვანე",
    5: "ლურჯი",
    6: "ვერცხლისფერი",
    7: "ყვითელი",
    8: "ნარინჯისფერი",
    9: "ყავისფერი",
    10: "ოქროსფერი",
    11: "ბორდოსფერი",
    12: "რუხი",
    13: "შავი მეტალიკი",
    14: "რუხი მეტალიკი",
    15: "მუქი ლურჯი",
    16: "ვერცხლისფერი მეტალიკი",
    17: "ბეჟი",
    18: "მწვანე მეტალიკი",
    19: "სხვა",
}
LOCATION_MAP = {
    1: "საქართველო",
    2: "თბილისი",
    3: "ბათუმი",
    4: "ქუთაისი",
    5: "რუსთავი",
    6: "გორი",
    7: "ფოთი",
    8: "ზუგდიდი",
    9: "ხაშური",
    10: "სამტრედია",
    11: "სენაკი",
    12: "ოზურგეთი",
    13: "მცხეთა",
    14: "ახალციხე",
    15: "მარნეული",
    16: "თელავი",
    17: "ბორჯომი",
    18: "ქობულეთი",
    19: "გარდაბანი",
    20: "კასპი",
}
CATEGORY_MAP = {
    1: "სედანი",
    2: "ჰეტჩბეკი",
    3: "უნივერსალი",
    4: "კუპე",
    5: "ჯიპი",
    6: "პიკაპი",
    7: "კაბრიოლეტი",
    8: "მინივენი",
    9: "მიკროავტობუსი",
    10: "ლიმუზინი",
    11: "ფურგონი",
    12: "სატვირთო",
    66: "კროსოვერი",
}
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


def _positive_int(value) -> int | None:
    # 0 -> None. myauto uses 0 for unknown numeric fields.
    n = _to_int(value)
    return n if n and n > 0 else None


def _cc_to_liters(cc: int | None) -> float | None:
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


def _build_description_from_api(item: dict) -> str:
    parts: list[str] = []
    raw = clean_text(item.get("car_desc") or "")
    if raw:
        parts.append(raw)
    flags = [label for key, label in FEATURE_FLAGS.items() if item.get(key)]
    if flags:
        parts.append("ოპციები: " + ", ".join(flags))
    if item.get("airbags"):
        parts.append(f"აირბაგები: {item.get('airbags')}")
    return "\n\n".join(parts)


def _build_phone_from_api(item: dict) -> str:
    # Listings endpoint returns phone masked ('995557607***'). Masked -> ''.
    raw = item.get("client_phone")
    if raw is None:
        return ""
    raw_str = str(raw)
    if "*" in raw_str:
        return ""
    return format_phone(raw_str)


def _build_vin_from_api(item: dict) -> str:
    raw = (item.get("vin") or "").strip().upper()
    if raw and "*" not in raw and is_valid_vin(raw):
        return raw
    in_desc = find_vin(item.get("car_desc") or "")
    if in_desc:
        return in_desc
    return ""


def _build_model_from_api(item: dict) -> str:
    name = (item.get("model_name") or "").strip()
    extra = (item.get("car_model") or "").strip()
    if not extra:
        return name
    if extra.lower() in name.lower():
        return name
    return f"{name} {extra}".strip()


def item_to_car(item: dict) -> Car | None:
    # Convert one API item -> Car. Returns None if missing required fields.
    car_id = item.get("car_id")
    if not car_id:
        return None

    has_catalyst = item.get("has_catalyst")
    return Car(
        source=SOURCE,
        source_id=str(car_id),
        url=DETAIL_URL_TEMPLATE.format(car_id=car_id),
        manufacturer=(item.get("man_name") or "").strip(),
        model=_build_model_from_api(item),
        year=_to_int(item.get("prod_year")),
        body_type=CATEGORY_MAP.get(item.get("category_id"), ""),
        price_amount=_positive_int(item.get("price")),
        price_currency=CURRENCY_MAP.get(item.get("currency_id"), ""),
        engine_volume_l=_cc_to_liters(_to_int(item.get("engine_volume"))),
        engine_type=FUEL_MAP.get(item.get("fuel_type_id"), ""),
        cylinders=_positive_int(item.get("cylinders")),
        power_hp=_positive_int(item.get("hp")),
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
        has_catalyst=(
            True if has_catalyst == 1 else False if has_catalyst == 2 else None
        ),
        tech_inspection=bool(item.get("tech_inspection"))
        if item.get("tech_inspection") is not None
        else None,
        vin=_build_vin_from_api(item),
        license_plate=(item.get("license_number") or "").strip(),
        location=LOCATION_MAP.get(item.get("location_id"), ""),
        seller_name=(item.get("client_name") or "").strip(),
        # masked in the listing API - fall back to a number written in the description
        phone=_build_phone_from_api(item)
        or phone_from_text(item.get("car_desc") or ""),
        posted_date=(item.get("order_date") or "").strip(),
        views=_to_int(item.get("views")),
        description=_build_description_from_api(item),
        video_url=(item.get("video_url") or "").strip(),
        image_urls=_build_image_urls(item),
    )


SPEC_TO_FIELD = {
    "მწარმოებელი": "manufacturer",
    "მოდელი": "model",
    "წელი": "year",
    "კატეგორია": "body_type",
    "გარბენი": "mileage_km",
    "საწვავის ტიპი": "engine_type",
    "ძრავის მოცულობა": "engine_volume_l",
    "ცილინდრები": "cylinders",
    "გადაცემათა კოლოფი": "gearbox",
    "წამყვანი თვლები": "drive_wheels",
    "კარები": "doors",
    "საჭე": "steering",
    "ფერი": "color",
    "სალონის ფერი": "interior_color",
    "სალონის მასალა": "interior_material",
    "ტექ. დათვალიერება": "tech_inspection",
    "კატალიზატორი": "has_catalyst",
    "მდგომარეობა": "condition",
    "ადგილების რაოდენობა": "seats",
    "სიმძლავრე": "power_hp",
}

_INT_RANGES = {
    "year": (1900, 2030),
    "mileage_km": (0, 2_000_000),
    "cylinders": (1, 16),
    "doors": (1, 8),
    "seats": (1, 50),
    "power_hp": (1, 2000),
}
_BOOL_FIELDS = {"tech_inspection", "has_catalyst"}


def _convert_spec_value(field: str, raw: str) -> object:
    # raw string -> whatever type the Car field expects
    if field == "engine_volume_l":
        return clean_engine_volume(raw)
    if field == "doors":
        first = raw.split("/")[0] if raw else ""
        return sane_int(first, *_INT_RANGES["doors"])
    if field in _INT_RANGES:
        lo, hi = _INT_RANGES[field]
        return sane_int(raw, lo, hi)
    if field in _BOOL_FIELDS:
        return parse_bool_yes_no(raw)
    if field == "steering":
        if "მარცხ" in raw:
            return "მარცხენა"
        if "მარჯვ" in raw:
            return "მარჯვენა"
        return ""
    return raw.strip()


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


_TITLE_RE = re.compile(r"^(\d{4})\s+(\S+)\s+(.*)$")


async def extract_title(page: Page) -> tuple[int | None, str, str]:
    # a title like "2014 Lexus ES 350 Base" -> (year, manufacturer, model)
    el = await page.query_selector("p.leading-\\[100\\%\\]")
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
    # the description lives in p.text-raisin-80.whitespace-pre-wrap
    el = await page.query_selector(
        'p[class*="text-raisin-80"][class*="whitespace-pre-wrap"]'
    )
    if not el:
        return ""
    return clean_text(await el.inner_text())


async def extract_photos(page: Page) -> list[str]:
    # photos: take the /large/ versions, rewriting thumbs into large
    photos: list[str] = []
    seen: set[str] = set()
    elements = await page.query_selector_all("img[src*='/photos/']")
    for el in elements:
        src = await el.get_attribute("src")
        if not src:
            continue
        large = src.replace("/thumbs/", "/large/")
        key = large.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        photos.append(large)
    return photos


_PHOTO_N_RE = re.compile(r"/large/(\d+)_(\d+)\.jpg")


def _ensure_all_photos(
    photos: list[str], car_id: str, max_photos: int = 40
) -> list[str]:
    # If the page lazy-loaded and only thumbs were in the HTML, build every
    # _1.jpg, _2.jpg ... _N.jpg URL anyway.
    #
    # Work the pattern out from the first URL, then add its variants.
    if not photos:
        return []

    first = photos[0]
    match = _PHOTO_N_RE.search(first)
    if not match:
        return photos

    base = first.split("_")[0]
    base_id = match.group(1)
    if base_id != car_id:
        return photos

    max_n = 1
    for p in photos:
        m = _PHOTO_N_RE.search(p)
        if m:
            max_n = max(max_n, int(m.group(2)))

    suffix = first[first.find(".jpg") :]

    return [f"{base}_{n}{suffix}" for n in range(1, min(max_n, max_photos) + 1)]


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
    # price and currency, read off the active currency switcher button
    result = await page.evaluate(_PRICE_AND_CURRENCY_JS)
    if not result:
        return None, ""

    amount = clean_int(result["price_text"])
    return amount, result["currency"]


_NO_VIN_MARKER = "გამყიდველს არ აქვს VIN კოდი"


async def extract_vin(page: Page, description: str) -> str:
    # from the VIN field when present, otherwise look in the description
    body_text = await page.evaluate("() => document.body.innerText")

    if _NO_VIN_MARKER in body_text:
        return find_vin(description)

    vin_from_page = find_vin(body_text)
    if vin_from_page:
        return vin_from_page

    return find_vin(description)


_MASK_CHARS = "*"


async def extract_phone(page: Page) -> str:
    # myauto hides the phone behind a login, so this returns empty.
    #
    # If some page does show a full number anyway (a test, a future feature, or a
    # cached state) it comes back formatted. otherwise ""
    link = await page.query_selector('a[data-testid^="show-number-modal-phone"]')
    if not link:
        link = await page.query_selector('a[href^="tel:+995"]:not([href*="32 280"])')

    if not link:
        return ""

    href = await link.get_attribute("href") or ""
    if _MASK_CHARS in href:
        return ""
    return format_phone(href)


async def extract_seller_name(page: Page) -> str:
    # the seller's name, when it is shown
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


GE_CITIES = (
    "თბილისი",
    "ბათუმი",
    "ქუთაისი",
    "რუსთავი",
    "გორი",
    "ფოთი",
    "ზუგდიდი",
    "ხაშური",
    "სამტრედია",
    "სენაკი",
    "ოზურგეთი",
    "მცხეთა",
    "ახალციხე",
    "მარნეული",
    "თელავი",
    "ბორჯომი",
    "ქობულეთი",
    "გარდაბანი",
    "კასპი",
    "წყალტუბო",
    "ჭიათურა",
    "ზესტაფონი",
    "ქარელი",
    "ცხინვალი",
    "ახალქალაქი",
    "ხონი",
    "ლანჩხუთი",
    "მესტია",
    "სიღნაღი",
    "ლაგოდეხი",
    "გურჯაანი",
    "დმანისი",
    "თეთრიწყარო",
    "ბოლნისი",
    "წალკა",
    "თიანეთი",
    "დუშეთი",
    "ცაგერი",
    "მარტვილი",
    "აბაშა",
    "ჩხოროწყუ",
    "წალენჯიხა",
    "ხობი",
    "ჩხალთა",
    "ცხაკაია",
)


async def extract_location(page: Page, spec: dict) -> str:
    # if the spec table has no city, try to get it from the page title
    for key in ("ადგილმდებარეობა", "ლოკაცია", "მდებარეობა", "ქალაქი"):
        if key in spec:
            return spec[key]

    title = await page.evaluate("() => document.title")
    for city in GE_CITIES:
        if city in title:
            return city
    return ""


async def scrape_one(
    context: BrowserContext,
    url: str,
    semaphore: asyncio.Semaphore | None = None,
) -> Car | None:
    # one detail page -> a Car, with retries
    #
    # the semaphore is optional. pass None for a manual smoke test
    if semaphore is None:
        semaphore = asyncio.Semaphore(1)

    async with semaphore:
        for attempt in range(RETRY_PER_CAR):
            page = await context.new_page()
            try:
                await page.route("**/*", block_heavy_resources)
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS
                )
                try:
                    await page.wait_for_selector(
                        'div[class*="py-[4px]"]', timeout=10_000
                    )
                except Exception:
                    title = await page.evaluate("() => document.title")
                    body_len = await page.evaluate(
                        "() => (document.body.innerText || '').length"
                    )
                    is_homepage = title.startswith("ახალი და მეორადი")
                    if is_homepage or body_len < 200:
                        return None
                    raise
                return await _build_car_from_page(page, url)
            except Exception as exc:
                if attempt == RETRY_PER_CAR - 1:
                    print(f"  [skip] {url.rsplit('/', 2)[-2]}: {type(exc).__name__}")
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
    location = await extract_location(page, spec)
    vin = await extract_vin(page, description)
    if vin and not is_valid_vin(vin):
        vin = ""

    spec_fields: dict[str, object] = {}
    for label, raw_value in spec.items():
        field = SPEC_TO_FIELD.get(label)
        if not field:
            continue
        spec_fields[field] = _convert_spec_value(field, raw_value)

    manufacturer = spec_fields.get("manufacturer") or manuf_t or ""
    model = spec_fields.get("model") or model_t or ""
    year = spec_fields.get("year") or year_t

    desc_parts = [description] if description else []
    if features:
        desc_parts.append("ოპციები: " + ", ".join(features))
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
        # tri-state: if we saw the features list it is True/False, if it was empty None (unknown).
        # `or None` would turn False into None too and lose that distinction.
        has_turbo=(any("ტურბო" in f.lower() for f in features) if features else None),
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


API_BASE = "https://api2.myauto.ge"

MYAUTO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) CLDB 2.1.3.08; Chrome/129.0.0.0; Safari/537.36"
)


async def _warmup(context: BrowserContext) -> None:
    # open myauto.ge first so the Cloudflare cookies get set
    #
    # Don't wait for the SPA to fully hydrate: take the response on `commit`, then
    # pause briefly for the cookies. domcontentloaded sometimes does not arrive
    # within 25s.
    page = await context.new_page()
    try:
        await page.route("**/*", block_heavy_resources)
        try:
            await page.goto(HOST, wait_until="commit", timeout=15_000)
        except Exception:
            pass
        await asyncio.sleep(3)
    finally:
        await page.close()


async def _fetch_page_raw(
    context: BrowserContext, page_num: int
) -> tuple[list[dict], int]:
    # Returns (items, last_page). items have FULL car data, not just IDs.
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

        async def _fetch():
            response = await context.request.get(
                f"{API_BASE}/ka/products",
                params=params,
                headers=headers,
                timeout=20_000,
            )
            if not response.ok:
                return None
            return await response.json()

        data = await asyncio.wait_for(_fetch(), timeout=25.0)
        if data is None:
            return [], 0
    except Exception as exc:  # including asyncio.TimeoutError, all handled the same way
        print(
            f"  API page {page_num} error: {type(exc).__name__}: {str(exc)[:80]}",
            flush=True,
        )
        return [], 0

    if data.get("statusCode") != 1:
        return [], 0

    payload = data.get("data") or {}
    items = payload.get("items") or []
    last_page = (payload.get("meta") or {}).get("last_page", 0)
    return items, last_page


async def _fetch_ids_page(
    context: BrowserContext, page_num: int
) -> tuple[list[str], int]:
    # Returns (car_ids, last_page). Legacy - kept for the HTML scrape path.
    items, last_page = await _fetch_page_raw(context, page_num)
    ids = [str(item["car_id"]) for item in items if item.get("car_id")]
    return ids, last_page


async def collect_all_ids(
    context: BrowserContext, max_pages: int | None = None
) -> list[str]:
    # walk every page and collect all car_ids, deduplicated
    print("  Warming up (visiting myauto.ge for CF cookies)...")
    await _warmup(context)

    print("  Fetching page 1 for total count...")
    first_ids, last_page = await _fetch_ids_page(context, 1)
    if not last_page:
        print("  Failed to reach API - got 0 pages")
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
        if page_num % 25 == 0 or page_num == last_page:
            print(
                f"  [API {page_num}/{last_page}] collected:{len(all_ids)}", flush=True
            )

    return all_ids


IDS_CACHE_PATH = Path(__file__).resolve().parents[2] / "exports" / "myauto-ids.json"


def _load_cached_ids() -> list[str] | None:
    if not IDS_CACHE_PATH.exists():
        return None
    try:
        data = json.loads(IDS_CACHE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception as exc:
        print(f"  [warn] failed to load IDs cache ({exc}); refetching")
    return None


def _save_cached_ids(ids: list[str]) -> None:
    IDS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    IDS_CACHE_PATH.write_text(json.dumps(ids), encoding="utf-8")
    print(f"  cached {len(ids)} ids to {IDS_CACHE_PATH}")


async def run(max_pages: int | None = None) -> None:
    # API-fast mode: each /products page returns full car data, not just IDs.
    # Single pass: fetch -> parse -> upsert. No per-car Playwright detail scrape.
    #
    # Speed: ~5-10 min for full ~50k cars. Tradeoffs:
    #   - Phones are masked in the listing endpoint (we store '') - same as HTML
    #   - Photo URLs are built from item.photo / item.pic_number (deterministic)
    #   - Description = car_desc + feature flags
    #
    # To use the slower HTML scrape per car instead, call run_html().
    print(f"MyAuto parser (API-fast mode, page-concurrency={CONCURRENT_PAGES})")

    already_saved = await get_existing_ids(SOURCE)
    print(f"  In DB: {len(already_saved)} listings")

    start_time = time.time()

    async with async_playwright() as playwright:
        browser, context = await create_stealth_context(playwright)
        try:
            print("  Warming up (visiting myauto.ge for CF cookies)...")
            await _warmup(context)

            print("  Fetching page 1 for total count...")
            first_items, last_page = await _fetch_page_raw(context, 1)
            if not last_page:
                print("  Failed to reach API")
                return
            if max_pages:
                last_page = min(last_page, max_pages)
            print(
                f"  Total: {last_page} pages × 30 = ~{last_page * 30} listings (with dedup ~half)"
            )

            buffer: list[Car] = []
            saved = 0
            seen_ids: set[str] = set(already_saved)

            def _consume(items: list[dict]) -> int:
                added = 0
                for item in items:
                    cid = str(item.get("car_id") or "")
                    if not cid or cid in seen_ids:
                        continue
                    seen_ids.add(cid)
                    try:
                        car = item_to_car(item)
                    except Exception as exc:
                        print(f"  [parse error] {cid}: {exc}", flush=True)
                        continue
                    if car:
                        buffer.append(car)
                        added += 1
                return added

            _consume(first_items)

            sem = asyncio.Semaphore(CONCURRENT_PAGES)

            async def _bounded_fetch(p):
                async with sem:
                    items, _ = await _fetch_page_raw(context, p)
                    return p, items

            tasks = [_bounded_fetch(p) for p in range(2, last_page + 1)]
            done_pages = 1

            for coro in asyncio.as_completed(tasks):
                p, items = await coro
                _consume(items)
                done_pages += 1

                if len(buffer) >= 250:
                    saved += await upsert_cars(buffer)
                    append_cars_to_csv(buffer, SOURCE)
                    buffer.clear()

                if done_pages % 25 == 0 or done_pages == last_page:
                    elapsed = time.time() - start_time
                    rate = done_pages / elapsed if elapsed else 0
                    eta = (last_page - done_pages) / rate if rate else 0
                    print(
                        f"  [{done_pages}/{last_page} pages] "
                        f"saved:{saved} buffer:{len(buffer)} "
                        f"rate:{rate:.1f} p/s ETA:{eta:.0f}s",
                        flush=True,
                    )

            if buffer:
                saved += await upsert_cars(buffer)
                append_cars_to_csv(buffer, SOURCE)
        finally:
            await context.close()
            await browser.close()

    print(f"\nDone in {time.time() - start_time:.0f}s. Saved: {saved} new cars.")


async def run_html(max_pages: int | None = None) -> None:
    # Slower HTML-detail scrape path (one Playwright page per car).
    #
    # Kept for reference / debugging. The API-fast `run()` is preferred.
    print(f"MyAuto parser (HTML scrape mode, concurrency={CONCURRENT_PAGES})")

    already_saved = await get_existing_ids(SOURCE)
    print(f"  In DB: {len(already_saved)} listings")

    start_time = time.time()

    async with async_playwright() as playwright:
        browser, context = await create_stealth_context(playwright)
        try:
            cached = _load_cached_ids() if max_pages is None else None
            if cached is not None:
                print(
                    f"  Loaded {len(cached)} IDs from cache (delete {IDS_CACHE_PATH.name} to refresh)"
                )
                all_ids = cached
            else:
                all_ids = await collect_all_ids(context, max_pages=max_pages)
                if max_pages is None:
                    _save_cached_ids(all_ids)

            new_ids = [cid for cid in all_ids if cid not in already_saved]
            print(
                f"  Found: {len(all_ids)} | New: {len(new_ids)} | "
                f"Skipping: {len(all_ids) - len(new_ids)}"
            )
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

        issues = validate_car(car)
        if issues:
            print(f"  [warn] {car.source_id}: {', '.join(issues[:3])}")

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
    # run one URL end to end. handy for debugging
    #
    # Usage:
    #     uv run python -c "from src.common.runtime import run as r; \\
    #         from src.parsers.myauto import smoke_test; \\
    #         r(smoke_test('https://www.myauto.ge/ka/pr/120183626/sale'))"
    async with async_playwright() as playwright:
        browser, context = await create_stealth_context(playwright)
        try:
            car = await scrape_one(context, url)
            if car:
                print(f"{car.source_id} {car.year} {car.manufacturer} {car.model}")
                print(f"{car.price_amount} {car.price_currency}, {car.mileage_km} km, "
                      f"{car.engine_volume_l} L {car.engine_type}, {car.gearbox}, "
                      f"{car.drive_wheels}, {car.color}, {car.steering}")
                print(f"vin {car.vin or '-'}, phone {car.phone or '-'}, "
                      f"{len(car.image_urls)} photos")
                print(car.description[:120])
            else:
                print("failed")
            return car
        finally:
            await context.close()
            await browser.close()


if __name__ == "__main__":
    import sys

    from src.common.runtime import run as _run_async

    args = sys.argv[1:]

    if args and args[0] == "smoke":
        target_url = (
            args[1] if len(args) > 1 else "https://www.myauto.ge/ka/pr/120183626/sale"
        )
        _run_async(smoke_test(target_url))
    elif args and args[0] == "test" and len(args) > 1:
        _run_async(run(max_pages=int(args[1])))
    else:
        _run_async(run())
