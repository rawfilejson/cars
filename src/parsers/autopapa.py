"""
AutoPapa.ge-ს პარსერი.

რა ხდება საერთო ჯამში:
  1. ვხსნით ბრაუზერს stealth-ის პარამეტრებით (იხ. common.anti_detection).
  2. ვათვალიერებთ საძიებო გვერდებს და ვაგროვებთ მანქანების ლინკებს.
  3. რესუმე — ჯერ ვამოწმებთ ბაზაში რა გვაქვს უკვე, რომ ხელახლა არ შევცადოთ.
  4. ერთდროულად რამდენიმე ფურცელში ვიხსნით თითო მანქანას და ვამოწერთ
     პარამეტრებს, აღწერას, ფოტოებს, ვინ კოდს და ა.შ.
  5. ბაზაში ვწერთ batch-ად (CONCURRENT_PAGES მანქანა ერთად).

ვინ-ის ლოგიკა:
  * ჯერ ვცდილობთ ღილაკზე დაჭერით (autopapa-ს colorbox popup ანახებს ვინ-ს).
  * მერე ვცდილობთ აღწერაში ვიპოვოთ (regex-ით, case-insensitive).
  * მერე AJAX endpoint-ით /get_vin/ge/{id}.
  * Asterisk-ით (ან წერტილებით) მასკირებული ვინ-ი — გამოვტოვებთ.
  * ყოველთვის დიდი ასოებით ვწერთ ბაზაში.

პარამეტრების ლოგიკა (მნიშვნელოვანი):
  autopapa-ს გვერდი მონაცემებს ორ ადგილას ინახავს:
    1. `.nameInfoObject` ბლოკი მარჯვნივ — წელი, ძარის ტიპი, გარბენი და ა.შ.
    2. `.comment-all` ფიჩერების ჩამონათვალი — გადაცემათა კოლოფი, საჭე,
       სალონის ფერი, მასალები, ცილინდრების რაოდენობა და ა.შ.
  ჩვენ ვამოღებთ ორივეს და ვაერთიანებთ — თუ რომელიმე ცარიელია, მეორედან ვცდილობთ.
"""

from __future__ import annotations

import asyncio
import re
import time

from playwright.async_api import BrowserContext, Page, async_playwright

from src.common.anti_detection import block_heavy_resources, create_stealth_context
from src.common.config import CONCURRENT_PAGES, PAGE_TIMEOUT_MS, RETRY_PER_CAR
from src.common.db import get_existing_ids, upsert_cars
from src.common.models import Car
from src.common.normalize import (
    clean_engine_volume,
    clean_int,
    clean_text,
    format_phone,
    normalize_steering,
    parse_customs,
    split_price,
)
from src.common.vin import best_vin


# ---------------------------------------------------------------------------
# კონფიგი
# ---------------------------------------------------------------------------

SOURCE = "autopapa"
HOST = "https://autopapa.ge"
START_URL = "https://autopapa.ge/ge/usd/search?order=date&page=1"


# ---------------------------------------------------------------------------
# დამხმარე ფუნქციები
# ---------------------------------------------------------------------------

# ID-ის ამოღება URL-დან: https://autopapa.ge/ge/usd/toyota/camry/905889 → 905889
_ID_FROM_URL_RE = re.compile(r"/(\d+)(?:[?#]|$)")


def extract_id(url: str) -> str:
    """URL-დან მანქანის id-ის გამოღება."""
    match = _ID_FROM_URL_RE.search(url)
    return match.group(1) if match else ""


def first_int(text: str | None) -> int | None:
    """პირველი მთლიანი რიცხვის ამოღება ტექსტიდან.

    "4/5"      → 4
    "4-5"      → 4
    "26 000"   → 26000
    "200 ც.ძ." → 200
    """
    if not text:
        return None
    match = re.search(r"\d+", str(text).replace(" ", " "))
    if not match:
        return None
    # თუ ციფრებს შორის space-ი არის (26 000) — გავაერთიანოთ
    extended = re.match(r"[\d\s]+", str(text)[match.start():])
    if extended:
        digits = re.sub(r"\D", "", extended.group(0))
        return int(digits) if digits else None
    return int(match.group(0))


def parse_features(text: str | None) -> dict[str, str]:
    """`.comment-all`-ის ტექსტიდან key:value პარამეტრების ამოღება.

    შესასვლელი ფორმატი:
        "ლუქი, გადაცემათა კოლოფი: ავტომატიკა, საჭე: მარცხენა, ABS, ..."

    გამოსავალი:
        {"გადაცემათა კოლოფი": "ავტომატიკა", "საჭე": "მარცხენა", ...}

    ფიჩერები რომელშიც ":" არ არის (ABS, ESP, ლუქი) უგულებელყოფილია.
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
    """ორი წყაროდან მონაცემები ერთად. InfoObject-ი უპირატესობით."""
    merged = dict(features)
    for key, value in info.items():
        if value:
            merged[key] = value
    return merged


def has_keyword(text: str | None, *keywords: str) -> bool:
    """რომელიმე keyword-ი ტექსტში არსებობს თუ არა."""
    if not text:
        return False
    return any(kw in text for kw in keywords)


# ---------------------------------------------------------------------------
# ლინკების კრება — საძიებო გვერდები
# ---------------------------------------------------------------------------


async def collect_listing_links(page: Page) -> list[str]:
    """ყველა საძიებო გვერდიდან მანქანის ლინკების კრება.

    autopapa-ს pagination მუშაობს რეგულარული next-ღილაკით (`a[rel=next]`).
    ვაგრძელებთ ვიდრე ღილაკი ფურცელზე არსებობს.
    """
    links: list[str] = []

    while True:
        for anchor in await page.query_selector_all("a.with_hash2"):
            href = await anchor.get_attribute("href")
            if href:
                links.append(HOST + href)

        next_btn = await page.query_selector("a[rel=next]")
        if not next_btn:
            break

        await next_btn.click()
        await page.wait_for_selector("div.boxCatalog2", timeout=PAGE_TIMEOUT_MS)

    # დუბლიკატების მოშორება + query string-ის გასუფთავება
    seen = dict.fromkeys(link.split("?")[0] for link in links)
    return list(seen)


# ---------------------------------------------------------------------------
# პარამეტრების ცხრილის წაკითხვა (InfoObject)
# ---------------------------------------------------------------------------

# JS კოდი — ერთი ფურცლიდან ვიღებთ ყველა .nameInfoObject-ს ერთად.
# უფრო სწრაფია ვიდრე ცალკ-ცალკე query_selector_all + await ციკლი.
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
    """InfoObject ცხრილის სრული dict — ქართული label-ი → value."""
    return await page.evaluate(_EXTRACT_PARAMS_JS)


# ---------------------------------------------------------------------------
# ვინ-ის ამოღება (სამი წყაროდან)
# ---------------------------------------------------------------------------


async def fetch_vin_by_click(page: Page) -> str:
    """1-ლი ცდა: ვინი ღილაკით.

    autopapa-ს ვინ ჩვეულებრივ დამალულია "VIN-ის გაგება" ღილაკის უკან —
    დაჭერით იხსნება popup და მასში წერია სრული ვინ.
    """
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
    """3-ე ცდა: პირდაპირ AJAX endpoint-ი.

    /get_vin/ge/{id} აბრუნებს მცირე HTML-ს, რომელშიც ნამდვილი ვინ წერია.
    """
    page = await context.new_page()
    try:
        await page.route("**/*", block_heavy_resources)
        await page.goto(
            f"{HOST}/get_vin/ge/{car_id}",
            wait_until="domcontentloaded",
            timeout=10_000,
        )
        return await page.content()
    except Exception:
        return ""
    finally:
        await page.close()


# ---------------------------------------------------------------------------
# კონტაქტი / location / გამყიდველი
# ---------------------------------------------------------------------------


async def extract_contact(page: Page) -> tuple[str, str]:
    """ლოკაცია (ქალაქი) + გამყიდველის სახელი.

    ფორმატი HTML-ში:
        რუსთავი, საქართველო   |   განუბაჟებელი
        Sopio Bekauri, დარეკეთ +995595...

    თუ გამყიდველის სახელი არ წერია — სტრიქონი იწყება ", დარეკეთ"-ით,
    seller სტრიქონი ცარიელად რჩება.
    """
    raw = await page.evaluate(
        "() => document.querySelector('.contactObjectNew > div')?.innerText?.trim() || ''"
    )
    lines = [line.strip() for line in raw.split("\n") if line.strip()]

    # ლოკაცია — პირველი ხაზიდან | სიმბოლომდე
    location = re.split(r"\s*\|\s*", lines[0])[0].strip() if lines else ""

    # გამყიდველი — მეორე ხაზიდან ", დარეკეთ"-მდე
    seller = ""
    if len(lines) > 1:
        # მოვაშოროთ ", დარეკეთ ..." და თუ რა დარჩა, ის გამყიდველის სახელია
        before_call = re.split(r",?\s*დარეკეთ", lines[1])[0].strip()
        # თუ ბოლოს მძიმე დარჩა (ცარიელი სახელის შემთხვევაში) — გავწმინდოთ
        seller = before_call.strip(",").strip()

    return location, seller


# ---------------------------------------------------------------------------
# Posted date + Views ამოღება
# ---------------------------------------------------------------------------


async def extract_meta(page: Page) -> tuple[int | None, str]:
    """`info-ads-page` ბლოკიდან ნახვების რაოდენობა + განთავსების თარიღი."""
    views: int | None = None
    posted = ""
    for item in await page.query_selector_all(".info-ads-page .item"):
        text = (await item.inner_text()).strip()
        if "ნახვა" in text:
            views = first_int(text)
        elif "განთავსებულია" in text:
            posted = text.replace("განთავსებულია:", "").strip()
    return views, posted


# ---------------------------------------------------------------------------
# ვიდეო და ფოტოები
# ---------------------------------------------------------------------------


async def extract_video(page: Page) -> str:
    """ვიდეოს URL — YouTube embed ან autopapa-ს გალერეიდან."""
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
    """ფოტოების URL-ების სია (გალერიის რიგით)."""
    photos: list[str] = []
    for el in await page.query_selector_all("a.hidden-galler-images"):
        href = await el.get_attribute("href")
        if href:
            photos.append(href)
    return photos


# ---------------------------------------------------------------------------
# ფასები
# ---------------------------------------------------------------------------


async def extract_prices(
    page: Page,
) -> tuple[int | None, str, int | None]:
    """ფასი + ვალუტა + ფასი განბაჟებით (USD).

    autopapa აჩვენებს:
      - მთავარი ფასი (გამყიდველის): "$31 000"
      - საქართველოში განბაჟებით: "$32 618" (current)
      - საწყისი ფასი (ძველი ტარიფი 2 აპრილამდე): "$32 514"
    ვინახავთ მთავარს და განბაჟებულს.
    """
    # მთავარი ფასი
    price_el = await page.query_selector(".priceObject")
    price_raw = (await price_el.inner_text()).strip() if price_el else ""
    price_amount, price_currency = split_price(price_raw)

    # ფასი განბაჟებით — ახალი ტარიფი (current)
    pwc_el = await page.query_selector(
        ".country-prices__card--current .country-prices__value"
    )
    price_with_customs = (
        first_int((await pwc_el.inner_text()).strip()) if pwc_el else None
    )

    return price_amount, price_currency, price_with_customs


# ---------------------------------------------------------------------------
# ერთი მანქანის scrape — სრულად
# ---------------------------------------------------------------------------


async def scrape_one(
    context: BrowserContext, url: str, semaphore: asyncio.Semaphore
) -> Car | None:
    """ერთი მანქანის სრული scrape. None-ის შემთხვევაში fail-ი იყო."""

    async with semaphore:
        for attempt in range(RETRY_PER_CAR):
            page = await context.new_page()
            try:
                await page.route("**/*", block_heavy_resources)
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS
                )
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


async def _build_car_from_page(
    context: BrowserContext, page: Page, url: str
) -> Car:
    """ერთი მანქანის გვერდიდან ყველაფრის ამოღება. dict → Car."""

    car_id = extract_id(url)

    # --- სათაური (Mercedes-Benz GLS 450 / Toyota Camry / ...) ---
    # firstChild-ით ვიღებთ მხოლოდ პირველ text node-ს, რომ ფასის კონვერტორი
    # ან მაგვარი ცალკეული ბავშვი ელემენტი არ ჩაერიოს.
    title = await page.evaluate(
        "() => document.querySelector('.titleObject')?.firstChild?.textContent?.trim() || ''"
    )
    title_parts = title.split()
    manufacturer = title_parts[0] if title_parts else ""
    model = " ".join(title_parts[1:]) if len(title_parts) > 1 else ""

    # --- პარამეტრები ორი წყაროდან: InfoObject + features ---
    info_params = await extract_info_params(page)

    # features text — .comment-all
    ca_el = await page.query_selector(".comment-all")
    features_text = (await ca_el.inner_text()).strip() if ca_el else ""
    feature_params = parse_features(features_text)

    # მონაცემები ერთად — InfoObject-ი ჯობნის features-ს თუ ორივეგან წერია
    params = merge_params(info_params, feature_params)

    # --- ფასები ---
    price_amount, price_currency, price_with_customs = await extract_prices(page)

    # --- ტელეფონი ---
    phone_el = await page.query_selector('a[href^="tel:"]')
    phone = (
        format_phone(await phone_el.get_attribute("href")) if phone_el else ""
    )

    # --- განბაჟება ---
    customs_el = await page.query_selector(".contactObjectNew nobr")
    customs_text = (await customs_el.inner_text()).strip() if customs_el else ""
    customs_cleared = parse_customs(customs_text)

    # --- ლოკაცია + გამყიდველი ---
    location, seller_name = await extract_contact(page)

    # --- აღწერა (features + გამყიდველის ტექსტი) ---
    cs_el = await page.query_selector(".comment-seller")
    seller_text = (await cs_el.inner_text()).strip() if cs_el else ""
    description = clean_text(features_text + "\n\n" + seller_text)

    # --- ნახვები + Posted ---
    views, posted = await extract_meta(page)

    # --- ვიდეო + ფოტოები ---
    video_url = await extract_video(page)
    image_urls = await extract_photos(page)

    # --- ვინ-ი (სამი წყაროდან — საუკეთესო) ---
    vin_from_click = await fetch_vin_by_click(page)
    vin_from_ajax = (
        await fetch_vin_via_ajax(context, car_id) if car_id else ""
    )
    vin = best_vin(vin_from_click, description, vin_from_ajax)

    # --- მთლიანი dict → Car მოდელი ---
    # გარბენი: "26 000 კმ. / 16 250 მილი" → 26000 (km only)
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
        cylinders=first_int(params.get("ცილინდრების რაოდენობა")),
        power_hp=first_int(params.get("სიმძლავრე")),
        has_turbo=has_keyword(features_text, "ტურბო"),
        gearbox=params.get("გადაცემათა კოლოფი", ""),
        drive_wheels=params.get("წამყვანი თვლები", ""),
        mileage_km=mileage,
        color=params.get("ძარის ფერი", ""),
        doors=first_int(params.get("კარები")),         # "4/5" → 4
        seats=first_int(params.get("ადგილების რაოდენობა")),  # "4-5" → 4
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def run() -> None:
    """მთავარი ციკლი — ლინკები → scrape → ბაზაში."""

    print(f"AutoPapa parser — {SOURCE}")
    print(f"  CONCURRENT_PAGES = {CONCURRENT_PAGES}")

    already_saved = await get_existing_ids(SOURCE)
    print(f"  ბაზაში უკვე გვაქვს: {len(already_saved)} მანქანა")

    start_time = time.time()

    async with async_playwright() as playwright:
        browser, context = await create_stealth_context(playwright)
        try:
            page = await context.new_page()
            await page.route("**/*", block_heavy_resources)
            await page.goto(START_URL, wait_until="domcontentloaded")
            await page.wait_for_selector("div.boxCatalog2")
            all_links = await collect_listing_links(page)
            await page.close()

            new_links = [
                link for link in all_links if extract_id(link) not in already_saved
            ]
            total = len(all_links)
            new = len(new_links)
            print(f"  სულ: {total} | ახალი: {new} | გამოტოვებული: {total - new}")

            if not new_links:
                print("ახალი მანქანა არ არის. დასრულდა.")
                return

            await _scrape_all(context, new_links, start_time)

        finally:
            await context.close()
            await browser.close()

    print(f"\nდასრულდა. სრული დრო: {time.time() - start_time:.0f} წმ.")


async def _scrape_all(
    context: BrowserContext, urls: list[str], start_time: float
) -> None:
    """ბევრი მანქანის scrape ერთდროულად + batch ჩაწერა ბაზაში."""

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

        buffer.append(car)

        if len(buffer) >= CONCURRENT_PAGES * 2:
            saved += await upsert_cars(buffer)
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


if __name__ == "__main__":
    from src.common.runtime import run as _run_async

    _run_async(run())
