import csv
import os
import re
import time
import asyncio
from playwright.async_api import async_playwright, ViewportSize, Route

CSV_FILE = 'autopapa.csv'
HOST = 'https://autopapa.ge'
START_URL = 'https://autopapa.ge/ge/usd/search?order=date&page=1'

CONCURRENT = 15
BATCH_FLUSH = 20
NAV_TIMEOUT = 25000
RETRY_PER_CAR = 2
MAX_IMAGES = 20

BLOCK_RESOURCES = {'image', 'media', 'font', 'stylesheet'}
BLOCK_DOMAINS = (
    'google-analytics.com', 'googletagmanager.com', 'facebook.net',
    'facebook.com', 'clarity.ms', 'addthis.com', 'siteheart.com',
    'doubleclick.net', 'recaptcha', 'gstatic.com', 'cloudflare-static',
)

FIELDS = [
    'ID', 'Source',
    'Manufacturer', 'Model', 'Year', 'Body_Type',
    'Price', 'Currency', 'Price_With_Customs',
    'Engine_Volume_L', 'Engine_Type', 'Cylinders', 'Has_Turbo', 'Power_HP',
    'Gearbox', 'Drive_Wheels',
    'Mileage_KM', 'Color', 'Doors', 'Seats', 'Interior_Color', 'Interior_Material',
    'Steering',
    'Condition', 'Customs_Cleared', 'Has_Catalyst', 'Tech_Inspection',
    'VIN', 'License_Plate',
    'Location', 'Seller_Name', 'Phone',
    'Posted_Date', 'Views',
    'URL',
    'Description',
    'Video_1',
] + [f'Image_{i}' for i in range(1, MAX_IMAGES + 1)]

VIN_RE = re.compile(r'\b[A-HJ-NPR-Z0-9]{17}\b')
NUM_RE = re.compile(r'[\d\s\u00a0]+')


def get_existing_ids():
    if not os.path.exists(CSV_FILE):
        return set()
    try:
        with open(CSV_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            if 'ID' not in (reader.fieldnames or []):
                return set()
            return {row['ID'] for row in reader if row.get('ID')}
    except Exception:
        return set()


def append_batch(rows: list, retries: int = 10) -> int:
    if not rows:
        return 0
    for attempt in range(retries):
        try:
            file_exists = os.path.exists(CSV_FILE) and os.path.getsize(CSV_FILE) > 0
            with open(CSV_FILE, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                if not file_exists:
                    writer.writeheader()
                writer.writerows(rows)
            return len(rows)
        except PermissionError:
            print(f'[CSV LOCKED — close Excel] retry {attempt + 1}/{retries}')
            time.sleep(3)
    return 0


def extract_id(url: str) -> str:
    m = re.search(r'/(\d+)(?:[?#]|$)', url)
    return m.group(1) if m else ''


def clean_int(s: str) -> str:
    if not s:
        return ''
    digits = ''.join(c for c in s if c.isdigit())
    return digits


def clean_decimal(s: str) -> str:
    if not s:
        return ''
    m = re.search(r'\d+(?:[.,]\d+)?', s)
    if not m:
        return ''
    return m.group(0).replace(',', '.')


def split_price(price: str):
    if not price:
        return '', ''
    if '$' in price:
        return clean_int(price), 'USD'
    if '€' in price:
        return clean_int(price), 'EUR'
    if 'L' in price or 'ლ' in price.lower():
        return clean_int(price), 'GEL'
    n = clean_int(price)
    return (n, 'USD') if n else ('', '')


def format_phone(raw: str) -> str:
    if not raw:
        return ''
    digits = re.sub(r'[^\d]', '', raw.replace('tel:', ''))
    if not digits:
        return ''
    if digits.startswith('995') and len(digits) >= 11:
        return '+' + digits
    if len(digits) == 9 and digits.startswith(('5', '7', '3')):
        return '+995' + digits
    if digits.startswith('7') and len(digits) == 11:
        return '+' + digits
    return '+' + digits


def normalize_steering(text: str) -> str:
    if not text:
        return ''
    if 'მარცხენა' in text:
        return 'მარცხენა'
    if 'მარჯვენა' in text:
        return 'მარჯვენა'
    return ''


def find_vin(text: str) -> str:
    if not text:
        return ''
    m = VIN_RE.search(text.upper())
    return m.group(0) if m else ''


def normalize_customs(s: str) -> str:
    if not s:
        return ''
    if 'განბაჟებული' in s and 'განუბაჟ' not in s:
        return 'განბაჟებული'
    if 'განუბაჟებელი' in s:
        return 'განუბაჟებელი'
    return s.strip()


async def block_unneeded(route: Route):
    req = route.request
    if req.resource_type in BLOCK_RESOURCES:
        return await route.abort()
    if any(d in req.url for d in BLOCK_DOMAINS):
        return await route.abort()
    await route.continue_()


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
    return list(dict.fromkeys(l.split('?')[0] for l in links))


async def extract_all_params(page) -> dict:
    return await page.evaluate('''
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
    ''')


async def fetch_vin_by_click(page) -> str:
    try:
        btn = await page.query_selector('button.hidden-vin')
        if not btn:
            return ''
        await btn.click()
        await page.wait_for_function(
            "() => { const el = document.querySelector('#cboxLoadedContent');"
            "return el && /[A-HJ-NPR-Z0-9]{17}/i.test(el.innerText); }",
            timeout=4000
        )
        content = await page.evaluate(
            '() => document.querySelector("#cboxLoadedContent")?.innerText || ""'
        )
        await page.evaluate('() => { try { $.colorbox.close(); } catch(e) {} }')
        return find_vin(content)
    except Exception:
        return ''


async def fetch_vin_ajax(context, car_id: str) -> str:
    try:
        p = await context.new_page()
        await p.route('**/*', block_unneeded)
        await p.goto(f'{HOST}/get_vin/ge/{car_id}',
                     wait_until='domcontentloaded', timeout=10000)
        content = await p.content()
        await p.close()
        return find_vin(content)
    except Exception:
        return ''


async def parse_contact(page):
    raw = await page.evaluate(
        '() => document.querySelector(".contactObjectNew > div")?.innerText?.trim() || ""'
    )
    lines = [l.strip() for l in raw.split('\n') if l.strip()]
    location = re.split(r'\s*\|\s*', lines[0])[0].strip() if lines else ''
    seller = re.split(r',\s*დარეკეთ', lines[1])[0].strip() if len(lines) > 1 else ''
    return location, seller


async def scrape_one(context, url: str, semaphore) -> dict | None:
    async with semaphore:
        for attempt in range(RETRY_PER_CAR):
            page = await context.new_page()
            try:
                await page.route('**/*', block_unneeded)
                await page.goto(url, wait_until='domcontentloaded', timeout=NAV_TIMEOUT)
                await page.wait_for_selector('.titleObject', timeout=8000)

                car_id = extract_id(url)
                params = await extract_all_params(page)

                title = await page.evaluate(
                    '() => document.querySelector(".titleObject")?.firstChild?.textContent?.trim() || ""'
                )
                parts = title.split()
                manufacturer = parts[0] if parts else ''
                model = ' '.join(parts[1:]) if len(parts) > 1 else ''

                phone_el = await page.query_selector('a[href^="tel:"]')
                phone = format_phone(await phone_el.get_attribute('href')) if phone_el else ''

                price_el = await page.query_selector('.priceObject')
                price_raw = (await price_el.inner_text()).strip() if price_el else ''
                price, currency = split_price(price_raw)

                pwc_el = await page.query_selector('.country-prices__card--current .country-prices__value')
                price_customs_raw = (await pwc_el.inner_text()).strip() if pwc_el else ''
                price_customs = clean_int(price_customs_raw)

                customs_el = await page.query_selector('.contactObjectNew nobr')
                customs = normalize_customs((await customs_el.inner_text()).strip() if customs_el else '')

                location, seller = await parse_contact(page)

                ca = await page.query_selector('.comment-all')
                cs = await page.query_selector('.comment-seller')
                features = (await ca.inner_text()).strip() if ca else ''
                seller_text = (await cs.inner_text()).strip() if cs else ''
                description = re.sub(r'\n{3,}', '\n\n', (features + '\n\n' + seller_text).strip())
                steering = normalize_steering(features)

                views, posted = '', ''
                for item in await page.query_selector_all('.info-ads-page .item'):
                    t = (await item.inner_text()).strip()
                    if 'ნახვა' in t:
                        views = clean_int(t)
                    elif 'განთავსებულია' in t:
                        posted = t.replace('განთავსებულია:', '').strip()

                video = ''
                for el in await page.query_selector_all('.thumbs .video a'):
                    href = await el.get_attribute('href')
                    if href and not href.startswith(('#', 'javascript:')):
                        video = href
                        break
                if not video:
                    iframe = await page.query_selector('#mainVideo iframe')
                    if iframe:
                        src = await iframe.get_attribute('src')
                        if src:
                            video = src

                photos = []
                for el in await page.query_selector_all('a.hidden-galler-images'):
                    href = await el.get_attribute('href')
                    if href:
                        photos.append(href)
                photos = photos[:MAX_IMAGES]

                vin = await fetch_vin_by_click(page) or find_vin(description)
                if not vin:
                    vin = await fetch_vin_ajax(context, car_id)

                mileage = clean_int(params.get('გარბენი', '').split('/')[0])
                engine_volume = clean_decimal(params.get('ძრავის მოცულობა', ''))

                row = {
                    'ID':                 car_id,
                    'Source':             'autopapa',
                    'Manufacturer':       manufacturer,
                    'Model':              model,
                    'Year':               clean_int(params.get('გამოშვების წელი', '')),
                    'Body_Type':          params.get('ძარის ტიპი', ''),
                    'Price':              price,
                    'Currency':           currency,
                    'Price_With_Customs': price_customs,
                    'Engine_Volume_L':    engine_volume,
                    'Engine_Type':        params.get('ძრავის ტიპი', ''),
                    'Cylinders':          clean_int(params.get('ცილინდრების რაოდენობა', '')),
                    'Has_Turbo':          '',
                    'Power_HP':           clean_int(params.get('სიმძლავრე', '')),
                    'Gearbox':            params.get('გადაცემათა კოლოფი', ''),
                    'Drive_Wheels':       params.get('წამყვანი თვლები', ''),
                    'Mileage_KM':         mileage,
                    'Color':              params.get('ძარის ფერი', ''),
                    'Doors':              params.get('კარები', ''),
                    'Seats':              params.get('ადგილების რაოდენობა', ''),
                    'Interior_Color':     params.get('სალონის ფერი', ''),
                    'Interior_Material':  params.get('სალონის მასალა', ''),
                    'Steering':           steering,
                    'Condition':          params.get('მდგომარეობა', ''),
                    'Customs_Cleared':    customs,
                    'Has_Catalyst':       '',
                    'Tech_Inspection':    '',
                    'VIN':                vin,
                    'License_Plate':      '',
                    'Location':           location,
                    'Seller_Name':        seller,
                    'Phone':              phone,
                    'Posted_Date':        posted,
                    'Views':              views,
                    'URL':                url,
                    'Description':        description,
                    'Video_1':            video,
                }
                for i in range(MAX_IMAGES):
                    row[f'Image_{i+1}'] = photos[i] if i < len(photos) else ''

                return row
            except Exception as e:
                if attempt == RETRY_PER_CAR - 1:
                    print(f'[FAIL] {url} — {e}')
                    return None
                await asyncio.sleep(1)
            finally:
                await page.close()
        return None


async def main():
    existing = get_existing_ids()
    print(f'Already saved: {len(existing)}')

    start = time.time()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ],
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/124.0.0.0 Safari/537.36',
            viewport=ViewportSize(width=1366, height=768),
            locale='ka-GE',
        )

        page = await context.new_page()
        await page.route('**/*', block_unneeded)
        await page.goto(START_URL, wait_until='domcontentloaded')
        await page.wait_for_selector('div.boxCatalog2')
        all_links = await collect_links(page)
        await page.close()

        new_links = [l for l in all_links if extract_id(l) not in existing]
        total, new = len(all_links), len(new_links)
        print(f'Total: {total} | Skipped: {total - new} | New: {new}')

        if not new_links:
            await browser.close()
            return

        semaphore = asyncio.Semaphore(CONCURRENT)
        tasks = [scrape_one(context, url, semaphore) for url in new_links]

        buffer, done, saved = [], 0, 0
        for coro in asyncio.as_completed(tasks):
            done += 1
            data = await coro
            if data:
                buffer.append(data)
                if len(buffer) >= BATCH_FLUSH:
                    saved += append_batch(buffer)
                    buffer.clear()
                if done % 5 == 0 or done == new:
                    elapsed = time.time() - start
                    rate = done / elapsed if elapsed else 0
                    eta = (new - done) / rate if rate else 0
                    print(f'[{done}/{new}] saved:{saved} '
                          f'rate:{rate:.1f}/s ETA:{eta:.0f}s '
                          f'last:{data["Manufacturer"]} {data["Model"]}')

        saved += append_batch(buffer)
        await browser.close()

    print(f'Done. Saved {saved}/{new} in {time.time() - start:.0f}s')


if __name__ == '__main__':
    asyncio.run(main())
