import csv
import os
import re
import time
import asyncio
from playwright.async_api import async_playwright, ViewportSize

CSV_FILE = 'DB.csv'
HOST = 'https://autopapa.ge'
START_URL = 'https://autopapa.ge/ge/usd/search?order=date&page=1'
CONCURRENT = 5
NAV_TIMEOUT = 30000

FIELDS = ['ID', 'Manufacturer', 'Model', 'Body_Type', 'Year', 'Price',
          'Price_With_Customs', 'Engine_Volume', 'Engine_Type', 'Power',
          'Mileage', 'Drive_Wheels', 'Steering', 'Doors', 'Seats',
          'Color', 'Condition', 'Customs', 'Location', 'Seller', 'Phone',
          'VIN', 'Views', 'Posted_Date', 'Description', 'URL', 'Media']


def get_existing_ids():
    if not os.path.exists(CSV_FILE):
        return set()
    try:
        with open(CSV_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            if 'ID' not in (reader.fieldnames or []):
                return set()
            return {row['ID'] for row in reader if row.get('ID')}
    except Exception as e:
        print(f'[WARN] read existing failed: {e}')
        return set()


def append_row(data: dict, retries: int = 10) -> bool:
    for attempt in range(retries):
        try:
            file_exists = os.path.exists(CSV_FILE) and os.path.getsize(CSV_FILE) > 0
            with open(CSV_FILE, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(data)
            return True
        except PermissionError:
            print(f'[CSV LOCKED — close Excel] retry {attempt + 1}/{retries}')
            time.sleep(3)
    print(f'[CSV LOST] ID:{data.get("ID")}')
    return False


def extract_id(url: str) -> str:
    m = re.search(r'/(\d+)(?:[?#]|$)', url)
    return m.group(1) if m else ''


def format_phone(raw: str) -> str:
    if not raw:
        return ''
    digits = re.sub(r'[^\d]', '', raw.replace('tel:', ''))
    return '+' + digits if digits else ''


def find_steering(text: str) -> str:
    if 'მარცხენა' in text:
        return 'მარცხენა'
    if 'მარჯვენა' in text:
        return 'მარჯვენა'
    return ''


VIN_RE = re.compile(r'\b[A-HJ-NPR-Z0-9]{17}\b')


def find_vin_in_text(text: str) -> str:
    m = VIN_RE.search(text.upper())
    return m.group(0) if m else ''


async def collect_links(page) -> list:
    links = []
    while True:
        for el in await page.query_selector_all('a.with_hash2'):
            href = await el.get_attribute('href')
            if href:
                links.append(HOST + href)
        next_btn = await page.query_selector('a[rel=next]')
        if not next_btn:
            break
        await next_btn.click()
        await page.wait_for_selector('div.boxCatalog2')
    return list(dict.fromkeys(l.split('?')[0] for l in links))  # dedupe, keep order


async def get_param(page, label: str) -> str:
    for el in await page.query_selector_all('.nameInfoObject'):
        text = await el.inner_text()
        if label in text:
            return text.replace(label, '').strip()
    return ''


async def fetch_vin_by_click(page) -> str:
    """დააჭერი hidden-vin ღილაკს, დაელოდე popup-ს, ამოიღე VIN"""
    try:
        btn = await page.query_selector('button.hidden-vin')
        if not btn:
            return ''
        await btn.click()
        await page.wait_for_function(
            "() => { const el = document.querySelector('#cboxLoadedContent');"
            "return el && /[A-HJ-NPR-Z0-9]{17}/i.test(el.innerText); }",
            timeout=6000
        )
        content = await page.evaluate(
            '() => document.querySelector("#cboxLoadedContent")?.innerText || ""'
        )
        await page.evaluate('() => { try { $.colorbox.close(); } catch(e) {} }')
        return find_vin_in_text(content)
    except Exception:
        return ''


async def fetch_vin_by_ajax(context, car_id: str) -> str:
    """Fallback — პირდაპირ AJAX endpoint-ი"""
    try:
        p = await context.new_page()
        await p.goto(f'{HOST}/get_vin/ge/{car_id}',
                     wait_until='domcontentloaded', timeout=15000)
        content = await p.content()
        await p.close()
        return find_vin_in_text(content)
    except Exception:
        return ''


async def parse_contact(page):
    """Location, Seller — .contactObjectNew-დან"""
    raw = await page.evaluate(
        '() => document.querySelector(".contactObjectNew > div")?.innerText?.trim() || ""'
    )
    lines = [l.strip() for l in raw.split('\n') if l.strip()]
    location = ''
    seller = ''
    if lines:
        # "რუსთავი (AUTOPAPA), საქართველო | განუბაჟებელი"
        first = lines[0]
        location = re.split(r'\s*\|\s*', first)[0].strip()
    if len(lines) > 1:
        # "Bekauri Sopio, დარეკეთ +995..."
        seller = re.split(r',\s*დარეკეთ', lines[1])[0].strip()
    return location, seller


async def scrape_listing(context, url: str, semaphore) -> dict | None:
    async with semaphore:
        page = await context.new_page()
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=NAV_TIMEOUT)
            await page.wait_for_selector('.titleObject', timeout=10000)

            car_id = extract_id(url)

            # Title — მხოლოდ პირველი text node
            title = await page.evaluate(
                '() => document.querySelector(".titleObject")?.firstChild?.textContent?.trim() || ""'
            )
            parts = title.split()
            manufacturer = parts[0] if parts else ''
            model = ' '.join(parts[1:]) if len(parts) > 1 else ''

            # Phone
            phone_el = await page.query_selector('a[href^="tel:"]')
            phone = format_phone(await phone_el.get_attribute('href')) if phone_el else ''

            # Price
            price_el = await page.query_selector('.priceObject')
            price = (await price_el.inner_text()).strip() if price_el else ''

            # Price with customs (GE)
            pwc_el = await page.query_selector('.country-prices__card--current .country-prices__value')
            price_customs = (await pwc_el.inner_text()).strip() if pwc_el else ''

            # Customs status
            customs_el = await page.query_selector('.contactObjectNew nobr')
            customs = (await customs_el.inner_text()).strip() if customs_el else ''

            # Location + Seller
            location, seller = await parse_contact(page)

            # Description
            ca = await page.query_selector('.comment-all')
            cs = await page.query_selector('.comment-seller')
            features = (await ca.inner_text()).strip() if ca else ''
            seller_text = (await cs.inner_text()).strip() if cs else ''
            description = (features + '\n' + seller_text).strip()
            steering = find_steering(features)

            # Views + Posted
            views = ''
            posted = ''
            for item in await page.query_selector_all('.info-ads-page .item'):
                t = (await item.inner_text()).strip()
                if 'ნახვა' in t:
                    views = re.sub(r'[^\d]', '', t)
                elif 'განთავსებულია' in t:
                    posted = t.replace('განთავსებულია:', '').strip()

            # Videos first
            videos = []
            for el in await page.query_selector_all('.thumbs .video a'):
                href = await el.get_attribute('href')
                if href and not href.startswith(('#', 'javascript:')):
                    videos.append(href)
            iframe = await page.query_selector('#mainVideo iframe')
            if iframe:
                src = await iframe.get_attribute('src')
                if src:
                    videos.append(src)

            # Photos after
            photos = []
            for el in await page.query_selector_all('a.hidden-galler-images'):
                href = await el.get_attribute('href')
                if href:
                    photos.append(href)

            media = ', '.join(videos + photos)

            # VIN — ჯერ click, მერე description, ბოლოს AJAX
            vin = await fetch_vin_by_click(page)
            if not vin:
                vin = find_vin_in_text(description)
            if not vin:
                vin = await fetch_vin_by_ajax(context, car_id)

            return {
                'ID':                 car_id,
                'Manufacturer':       manufacturer,
                'Model':              model,
                'Body_Type':          await get_param(page, 'ძარის ტიპი:'),
                'Year':               await get_param(page, 'გამოშვების წელი:'),
                'Price':              price,
                'Price_With_Customs': price_customs,
                'Engine_Volume':      await get_param(page, 'ძრავის მოცულობა:'),
                'Engine_Type':        await get_param(page, 'ძრავის ტიპი:'),
                'Power':              await get_param(page, 'სიმძლავრე:'),
                'Mileage':            await get_param(page, 'გარბენი:'),
                'Drive_Wheels':       await get_param(page, 'წამყვანი თვლები:'),
                'Steering':           steering,
                'Doors':              await get_param(page, 'კარები:'),
                'Seats':              await get_param(page, 'ადგილების რაოდენობა:'),
                'Color':              await get_param(page, 'ძარის ფერი:'),
                'Condition':          await get_param(page, 'მდგომარეობა:'),
                'Customs':            customs,
                'Location':           location,
                'Seller':             seller,
                'Phone':              phone,
                'VIN':                vin,
                'Views':              views,
                'Posted_Date':        posted,
                'Description':        description,
                'URL':                url,
                'Media':              media,
            }
        except Exception as e:
            print(f'[ERROR] {url} — {e}')
            return None
        finally:
            await page.close()


async def main():
    existing = get_existing_ids()
    print(f'Already saved: {len(existing)}')

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/124.0.0.0 Safari/537.36',
            viewport=ViewportSize(width=1366, height=768),
            locale='ka-GE',
        )

        page = await context.new_page()
        await page.goto(START_URL, wait_until='domcontentloaded')
        await page.wait_for_selector('div.boxCatalog2')
        all_links = await collect_links(page)
        await page.close()

        new_links = [l for l in all_links if extract_id(l) not in existing]
        total = len(all_links)
        new = len(new_links)
        print(f'Total on site: {total} | Skipped (already saved): {total - new} | New: {new}')

        if not new_links:
            await browser.close()
            return

        semaphore = asyncio.Semaphore(CONCURRENT)
        tasks = [scrape_listing(context, url, semaphore) for url in new_links]

        done = 0
        saved = 0
        for coro in asyncio.as_completed(tasks):
            done += 1
            data = await coro
            if data:
                if append_row(data):
                    saved += 1
                print(f'[{done}/{new}] saved:{saved} ID:{data["ID"]} '
                      f'{data["Manufacturer"]} {data["Model"]}')
            else:
                print(f'[{done}/{new}] FAILED')

        await browser.close()
    print(f'Done. Saved {saved}/{new} new cars.')


asyncio.run(main())