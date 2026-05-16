import asyncio
import csv
import os
import re
import time
from playwright.async_api import async_playwright

CSV_FILE = 'MyAuto.csv'
API_BASE = 'https://api2.myauto.ge/ka/products'
DICT_URL = 'https://api2.myauto.ge/ka/appdata/other'
WARMUP_URL = 'https://www.myauto.ge/ka/s/iyideba-manqanebi?Page=1'
LIST_URL = 'https://www.myauto.ge/ka/pr/{car_id}/sale'
IMAGE_URL = 'https://static.my.ge/myauto/photos/{photo}/large/{car_id}_{n}.jpg'

CONCURRENT_PAGES = 25
BATCH_FLUSH = 200
MAX_IMAGES = 20
PER_PAGE = 30
RETRY_PAGE = 3
TIMEOUT_MS = 30000

VIN_RE = re.compile(r'\b[A-HJ-NPR-Z0-9]{17}\b')

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


CURRENCY_MAP = {1: 'USD', 2: 'EUR', 3: 'GEL'}

FUEL_FALLBACK = {
    1: 'ჰიბრიდი', 2: 'ბენზინი', 3: 'დიზელი', 4: 'ელექტრო',
    5: 'ბენზინი/გაზი', 6: 'ჰიბრიდი', 7: 'დატენვადი ჰიბრიდი',
}
GEAR_FALLBACK = {1: 'მექანიკა', 2: 'ავტომატიკა', 3: 'ტიპტრონიკი', 4: 'ვარიატორი'}
DRIVE_FALLBACK = {1: 'წინა', 2: 'უკანა', 3: '4x4'}
DOOR_FALLBACK = {1: '2/3', 2: '4/5', 3: '6+'}
MATERIAL_FALLBACK = {1: 'ტყავი', 2: 'ნაჭერი', 3: 'ველვეტი', 4: 'კომბინირებული', 5: 'სხვა'}

API_HEADERS = {
    'accept': '*/*',
    'accept-language': 'ka',
    'origin': 'https://www.myauto.ge',
    'referer': 'https://www.myauto.ge/',
    'sec-ch-ua': '"Not/A)Brand";v="8", "Chromium";v="129", "Google Chrome";v="129"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-site',
    'content-type': 'application/json',
}

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) CLDB 2.1.3.08; Chrome/129.0.0.0; Safari/537.36'
)


def reset_csv():
    with open(CSV_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()


def append_batch(rows, retries=10):
    if not rows:
        return 0
    for attempt in range(retries):
        try:
            with open(CSV_FILE, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                writer.writerows(rows)
            return len(rows)
        except PermissionError:
            print(f'[CSV LOCKED — close Excel] retry {attempt + 1}/{retries}')
            time.sleep(3)
    return 0


def format_phone(raw: str) -> str:
    if not raw:
        return ''
    cleaned = raw.strip()
    digits_and_stars = re.sub(r'[^\d*]', '', cleaned)
    if not digits_and_stars:
        return ''
    if digits_and_stars.startswith('995'):
        return '+' + digits_and_stars
    if digits_and_stars.startswith(('5', '7', '3')) and len(digits_and_stars) >= 9:
        return '+995' + digits_and_stars
    return '+' + digits_and_stars


def find_vin(text: str) -> str:
    if not text:
        return ''
    m = VIN_RE.search(text.upper())
    return m.group(0) if m else ''


def to_int_str(x) -> str:
    if x is None or x == '':
        return ''
    try:
        return str(int(x))
    except (ValueError, TypeError):
        return ''


def lookup(table: dict, key, fallback: dict) -> str:
    if key is None or key == 0:
        return ''
    if key in table:
        return table[key]
    return fallback.get(key, '')


async def fetch_json(api_context, url, params=None):
    for attempt in range(RETRY_PAGE):
        try:
            response = await api_context.get(url, params=params, timeout=TIMEOUT_MS)
            if response.status == 200:
                return await response.json()
            if response.status in (429, 503):
                await asyncio.sleep(2 + attempt * 2)
                continue
            return None
        except Exception:
            await asyncio.sleep(1 + attempt)
    return None


DICT_URLS = [
    'https://api2.myauto.ge/ka/appdata/other',
    'https://api2.myauto.ge/ka/dictionaries/get',
    'https://api2.myauto.ge/en/appdata/other',
]

COLOR_FALLBACK = {
    1: 'თეთრი', 2: 'შავი', 3: 'წითელი', 4: 'მწვანე', 5: 'ლურჯი',
    6: 'ვერცხლისფერი', 7: 'ყვითელი', 8: 'ნარინჯისფერი', 9: 'ყავისფერი',
    10: 'ოქროსფერი', 11: 'ბორდოსფერი', 12: 'რუხი', 13: 'შავი მეტალიკი',
    14: 'რუხი მეტალიკი', 15: 'მუქი ლურჯი', 16: 'ვერცხლისფერი მეტალიკი',
    17: 'ბეჟი', 18: 'მწვანე მეტალიკი', 19: 'სხვა',
}

LOCATION_FALLBACK = {
    1: 'საქართველო', 2: 'თბილისი', 3: 'ბათუმი', 4: 'ქუთაისი', 5: 'რუსთავი',
    6: 'გორი', 7: 'ფოთი', 8: 'ზუგდიდი', 9: 'ხაშური', 10: 'სამტრედია',
    11: 'სენაკი', 12: 'ოზურგეთი', 13: 'მცხეთა', 14: 'ახალციხე', 15: 'მარნეული',
    16: 'თელავი', 17: 'ბორჯომი', 18: 'ქობულეთი', 19: 'გარდაბანი', 20: 'კასპი',
    21: 'საგარეჯო', 22: 'წყალტუბო', 23: 'ცაგერი', 24: 'ჭიათურა', 25: 'ხონი',
    26: 'ლანჩხუთი', 27: 'ჭიათურა', 28: 'წნორი', 29: 'ახმეტა', 30: 'ლაგოდეხი',
    31: 'სიღნაღი', 32: 'წალენჯიხა', 33: 'ჩხოროწყუ', 34: 'მესტია', 35: 'ამბროლაური',
    80: 'ბაკურიანი',
}

CATEGORY_FALLBACK = {
    1: 'სედანი', 2: 'ჰეტჩბეკი', 3: 'უნივერსალი', 4: 'კუპე', 5: 'ჯიპი',
    6: 'პიკაპი', 7: 'კაბრიოლეტი', 8: 'მინივენი', 9: 'მიკროავტობუსი',
    10: 'ლიმუზინი', 11: 'ფურგონი', 12: 'სატვირთო', 13: 'მოტოციკლი',
    14: 'სკუტერი', 15: 'ATV', 30: 'მინივენი', 66: 'კროსოვერი',
}


async def fetch_dicts(api_context) -> dict:
    dicts = {
        'fuel': {}, 'gear': {}, 'drive': {}, 'color': {}, 'saloon_color': {},
        'location': {}, 'category': {}, 'door': {}, 'material': {},
    }
    data = None
    for url in DICT_URLS:
        data = await fetch_json(api_context, url)
        if data and (data.get('data') or data.get('Data')):
            print(f'Dict source: {url}')
            break
        data = None
    if not data:
        print('[WARN] dict fetch failed (all endpoints), using fallbacks')
        return dicts
    root = data.get('data', data.get('Data', {}))
    for item in root.get('FuelTypes', []) or []:
        dicts['fuel'][item.get('fuel_type_id') or item.get('id')] = item.get('title', '')
    for item in root.get('GearTypes', []) or []:
        dicts['gear'][item.get('gear_type_id') or item.get('id')] = item.get('title', '')
    for item in root.get('DriveTypes', []) or []:
        dicts['drive'][item.get('drive_type_id') or item.get('id')] = item.get('title', '')
    for item in root.get('Colors', []) or []:
        cid = item.get('color_id') or item.get('id')
        title = item.get('title', '')
        dicts['color'][cid] = title
        dicts['saloon_color'][cid] = title
    for item in root.get('Locations', []) or []:
        dicts['location'][item.get('location_id') or item.get('id')] = item.get('title', '')
    for item in root.get('Categories', []) or []:
        dicts['category'][item.get('category_id') or item.get('id')] = item.get('title', '')
    for item in root.get('DoorTypes', []) or []:
        dicts['door'][item.get('door_type_id') or item.get('id')] = item.get('title', '')
    for item in root.get('SaloonMaterials', []) or []:
        dicts['material'][item.get('saloon_material_id') or item.get('id')] = item.get('title', '')
    return dicts


def build_description(item: dict) -> str:
    parts = []
    raw = safe_str(item.get('car_desc'))
    raw = re.sub(r'\n{3,}', '\n\n', raw)
    if raw:
        parts.append(raw)

    flags = []
    flag_map = {
        'abs': 'ABS', 'esd': 'ESP', 'el_windows': 'ელ. შუშები',
        'conditioner': 'კონდინციონერი', 'climat_control': 'კლიმატკონტროლი',
        'leather': 'ტყავის სალონი', 'disks': 'ალუმინის დისკები',
        'nav_system': 'ნავიგაცია', 'central_lock': 'ცენტრალური საკეტი',
        'hatch': 'ლუქი', 'alarm': 'სიგნალიზაცია',
        'board_comp': 'ბორტკომპიუტერი', 'hydraulics': 'ჰიდრო',
        'chair_warming': 'სავარძლების გათბობა', 'obstacle_indicator': 'პარკტრონიკი',
        'back_camera': 'უკანა კამერა', 'start_stop': 'Start/Stop',
        'has_turbo': 'ტურბო', 'tech_inspection': 'ტექდათვალიერება',
    }
    for k, label in flag_map.items():
        if item.get(k):
            flags.append(label)
    if flags:
        parts.append('ფუნქციები: ' + ', '.join(flags))

    if item.get('airbags'):
        parts.append(f'აირბაგები: {item["airbags"]}')

    return '\n\n'.join(parts)


def build_images(item: dict) -> list:
    car_id = item.get('car_id')
    photo = item.get('photo', '')
    pic_n = item.get('pic_number') or 0
    if not (car_id and photo and pic_n):
        return []
    photo_ver = item.get('photo_ver', '')
    urls = []
    for i in range(1, min(pic_n, MAX_IMAGES) + 1):
        url = IMAGE_URL.format(photo=photo, car_id=car_id, n=i)
        if photo_ver:
            url += f'?v={photo_ver}'
        urls.append(url)
    return urls


def safe_str(x) -> str:
    if x is None:
        return ''
    return str(x).strip()


def process_item(item: dict, dicts: dict):
    if not isinstance(item, dict):
        return None
    car_id = item.get('car_id')
    if not car_id:
        return None

    man = safe_str(item.get('man_name'))
    model_name = safe_str(item.get('model_name'))
    car_model_extra = safe_str(item.get('car_model'))
    model = model_name
    if car_model_extra and car_model_extra.lower() not in model.lower():
        model = (model_name + ' ' + car_model_extra).strip()

    currency_id = item.get('currency_id')
    currency = CURRENCY_MAP.get(currency_id, '')
    price = to_int_str(item.get('price'))

    engine_cc = item.get('engine_volume')
    engine_l = ''
    if engine_cc:
        try:
            engine_l = f'{int(engine_cc) / 1000:.1f}'
        except (ValueError, TypeError):
            engine_l = ''

    mileage = to_int_str(item.get('car_run_km') or item.get('car_run'))

    steering = 'მარჯვენა' if item.get('right_wheel') else 'მარცხენა'

    vin_raw = safe_str(item.get('vin'))
    if vin_raw and '*' not in vin_raw:
        vin = vin_raw
    else:
        vin = find_vin(safe_str(item.get('car_desc')))
        if not vin and vin_raw:
            vin = vin_raw

    customs = 'განბაჟებული' if item.get('customs_passed') else 'განუბაჟებელი'

    seller_name = safe_str(item.get('client_name'))
    phone = format_phone(safe_str(item.get('client_phone')))

    posted = safe_str(item.get('order_date'))
    views = to_int_str(item.get('views'))

    url = LIST_URL.format(car_id=car_id)
    video = safe_str(item.get('video_url'))

    images = build_images(item)

    row = {
        'ID':                 str(car_id),
        'Source':             'myauto',
        'Manufacturer':       man,
        'Model':              model,
        'Year':               to_int_str(item.get('prod_year')),
        'Body_Type':          lookup(dicts['category'], item.get('category_id'), CATEGORY_FALLBACK),
        'Price':              price,
        'Currency':           currency,
        'Price_With_Customs': '',
        'Engine_Volume_L':    engine_l,
        'Engine_Type':        lookup(dicts['fuel'], item.get('fuel_type_id'), FUEL_FALLBACK),
        'Cylinders':          to_int_str(item.get('cylinders')),
        'Has_Turbo':          'კი' if item.get('has_turbo') else '',
        'Power_HP':           to_int_str(item.get('hp')),
        'Gearbox':            lookup(dicts['gear'], item.get('gear_type_id'), GEAR_FALLBACK),
        'Drive_Wheels':       lookup(dicts['drive'], item.get('drive_type_id'), DRIVE_FALLBACK),
        'Mileage_KM':         mileage,
        'Color':              lookup(dicts['color'], item.get('color_id'), COLOR_FALLBACK),
        'Doors':              lookup(dicts['door'], item.get('door_type_id'), DOOR_FALLBACK),
        'Seats':              '',
        'Interior_Color':     lookup(dicts['saloon_color'], item.get('saloon_color_id'), COLOR_FALLBACK),
        'Interior_Material':  lookup(dicts['material'], item.get('saloon_material_id'), MATERIAL_FALLBACK),
        'Steering':           steering,
        'Condition':          '',
        'Customs_Cleared':    customs,
        'Has_Catalyst':       'კი' if item.get('has_catalyst') == 1 else ('არა' if item.get('has_catalyst') == 2 else ''),
        'Tech_Inspection':    'კი' if item.get('tech_inspection') else '',
        'VIN':                vin,
        'License_Plate':      safe_str(item.get('license_number')),
        'Location':           lookup(dicts['location'], item.get('location_id'), LOCATION_FALLBACK),
        'Seller_Name':        seller_name,
        'Phone':              phone,
        'Posted_Date':        posted,
        'Views':              views,
        'URL':                url,
        'Description':        build_description(item),
        'Video_1':            video,
    }
    for i in range(MAX_IMAGES):
        row[f'Image_{i+1}'] = images[i] if i < len(images) else ''
    return row


async def fetch_listing_page(api_context, page_num):
    params = {
        'TypeID': '0',
        'ForRent': 'false',
        'CurrencyID': '3',
        'MileageType': '1',
        'Page': str(page_num),
    }
    return await fetch_json(api_context, API_BASE, params=params)


async def main():
    print('Resetting MyAuto.csv...')
    reset_csv()

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
            user_agent=USER_AGENT,
            locale='ka-GE',
            extra_http_headers=API_HEADERS,
        )

        print('Warming up (visiting myauto.ge for clearance)...')
        warmup_page = await context.new_page()
        try:
            await warmup_page.goto(WARMUP_URL, wait_until='domcontentloaded', timeout=60000)
            await warmup_page.wait_for_timeout(3000)
        except Exception as e:
            print(f'[WARN] warmup partial: {e}')
        await warmup_page.close()

        api_context = context.request

        print('Fetching dictionaries...')
        dicts = await fetch_dicts(api_context)
        sizes = {k: len(v) for k, v in dicts.items()}
        print(f'Dictionaries loaded: {sizes}')

        print('Fetching page 1 to discover total...')
        first = await fetch_listing_page(api_context, 1)
        if not first or first.get('statusCode') != 1:
            print('Failed to fetch first page. Exiting.')
            await browser.close()
            return

        meta = first.get('data', {}).get('meta', {})
        total = meta.get('total', 0)
        last_page = meta.get('last_page', 0)
        per_page = meta.get('per_page', PER_PAGE)
        print(f'Total cars: {total} | Pages: {last_page} | Per page: {per_page}')

        buffer = []
        saved = 0

        for item in first.get('data', {}).get('items', []) or []:
            try:
                row = process_item(item, dicts)
                if row:
                    buffer.append(row)
            except Exception as e:
                print(f'[SKIP item] {e}')

        sem = asyncio.Semaphore(CONCURRENT_PAGES)

        async def get_page(p_num):
            async with sem:
                return p_num, await fetch_listing_page(api_context, p_num)

        tasks = [get_page(p) for p in range(2, last_page + 1)]

        done_pages = 1
        failed_pages = 0
        for coro in asyncio.as_completed(tasks):
            page_num, data = await coro
            done_pages += 1
            if not data:
                failed_pages += 1
                continue
            items = data.get('data', {}).get('items', []) or []
            for item in items:
                try:
                    row = process_item(item, dicts)
                    if row:
                        buffer.append(row)
                except Exception as e:
                    print(f'[SKIP item page {page_num}] {e}')

            if len(buffer) >= BATCH_FLUSH:
                saved += append_batch(buffer)
                buffer.clear()

            if done_pages % 20 == 0 or done_pages == last_page:
                elapsed = time.time() - start
                rate = done_pages / elapsed if elapsed else 0
                eta = (last_page - done_pages) / rate if rate else 0
                print(f'[{done_pages}/{last_page}] saved:{saved + len(buffer)} '
                      f'failed:{failed_pages} pages/s:{rate:.1f} ETA:{eta:.0f}s')

        saved += append_batch(buffer)
        await browser.close()

    print(f'Done. Saved {saved} cars in {time.time() - start:.0f}s. Failed pages: {failed_pages}')


if __name__ == '__main__':
    asyncio.run(main())
