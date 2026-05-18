import asyncio
import csv
import os
import re
import time
from playwright.async_api import async_playwright

CSV_FILE = 'MyAuto.csv'
AUTH_FILE = 'auth.json'
LIST_URL = (
    'https://myauto.ge/ka/s/iyideba-manqanebi'
    '?vehicleType=0&bargainType=0&currId=1&mileageType=1&layoutId=1&page={page}'
)
CAR_URL = 'https://www.myauto.ge/ka/pr/{car_id}/sale'
IMAGE_URL = 'https://static.my.ge/myauto/photos/{photo}/large/{car_id}_{n}.jpg'
API_HOST = 'api2.myauto.ge'
API_PATH = '/ka/products'
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) CLDB 2.1.3.08; Chrome/129.0.0.0; Safari/537.36'
)

CONCURRENT = 10
MAX_IMAGES = 20
BATCH_FLUSH = 200
PAGE_TIMEOUT = 25000
API_WAIT = 20

VIN_RE = re.compile(r'\b[A-HJ-NPR-Z0-9]{17}\b') # patara asoebit tu weria uppercase daamate

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

FUEL_FB = {
    1: 'ჰიბრიდი', 2: 'ბენზინი', 3: 'დიზელი', 4: 'ელექტრო',
    5: 'ბენზინი/გაზი', 6: 'ჰიბრიდი', 7: 'დატენვადი ჰიბრიდი',
}
GEAR_FB = {1: 'მექანიკა', 2: 'ავტომატიკა', 3: 'ტიპტრონიკი', 4: 'ვარიატორი'}
DRIVE_FB = {1: 'წინა', 2: 'უკანა', 3: '4x4'}
DOOR_FB = {1: '2/3', 2: '4/5', 3: '6+'}
MATERIAL_FB = {1: 'ტყავი', 2: 'ნაჭერი', 3: 'ველვეტი', 4: 'კომბინირებული', 5: 'სხვა'}
COLOR_FB = {
    1: 'თეთრი', 2: 'შავი', 3: 'წითელი', 4: 'მწვანე', 5: 'ლურჯი',
    6: 'ვერცხლისფერი', 7: 'ყვითელი', 8: 'ნარინჯისფერი', 9: 'ყავისფერი',
    10: 'ოქროსფერი', 11: 'ბორდოსფერი', 12: 'რუხი', 13: 'შავი მეტალიკი',
    14: 'რუხი მეტალიკი', 15: 'მუქი ლურჯი', 16: 'ვერცხლისფერი მეტალიკი',
    17: 'ბეჟი', 18: 'მწვანე მეტალიკი', 19: 'სხვა',
}
LOCATION_FB = {
    1: 'საქართველო', 2: 'თბილისი', 3: 'ბათუმი', 4: 'ქუთაისი', 5: 'რუსთავი',
    6: 'გორი', 7: 'ფოთი', 8: 'ზუგდიდი', 9: 'ხაშური', 10: 'სამტრედია',
    11: 'სენაკი', 12: 'ოზურგეთი', 13: 'მცხეთა', 14: 'ახალციხე', 15: 'მარნეული',
    16: 'თელავი', 17: 'ბორჯომი', 18: 'ქობულეთი', 19: 'გარდაბანი', 20: 'კასპი',
    21: 'საგარეჯო', 22: 'წყალტუბო', 23: 'ცაგერი', 24: 'ჭიათურა', 25: 'ხონი',
    26: 'ლანჩხუთი', 27: 'ჭიათურა', 28: 'წნორი', 29: 'ახმეტა', 30: 'ლაგოდეხი',
    31: 'სიღნაღი', 32: 'წალენჯიხა', 33: 'ჩხოროწყუ', 34: 'მესტია', 35: 'ამბროლაური',
    80: 'ბაკურიანი',
}
CATEGORY_FB = {
    1: 'სედანი', 2: 'ჰეტჩბეკი', 3: 'უნივერსალი', 4: 'კუპე', 5: 'ჯიპი',
    6: 'პიკაპი', 7: 'კაბრიოლეტი', 8: 'მინივენი', 9: 'მიკროავტობუსი',
    10: 'ლიმუზინი', 11: 'ფურგონი', 12: 'სატვირთო', 13: 'მოტოციკლი',
    14: 'სკუტერი', 15: 'ATV', 30: 'მინივენი', 66: 'კროსოვერი',
}

BLOCK_DOMAINS = (
    'google-analytics.com', 'googletagmanager.com', 'facebook.net',
    'hotjar.com', 'clarity.ms', 'addthis.com', 'doubleclick.net',
    'recaptcha.net', 'adocean.pl', 'livecaller.io',
)


def reset_csv():
    with open(CSV_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        csv.DictWriter(f, fieldnames=FIELDS).writeheader()


def append_batch(rows, retries=10):
    if not rows:
        return 0
    for attempt in range(retries):
        try:
            with open(CSV_FILE, 'a', newline='', encoding='utf-8-sig') as f:
                csv.DictWriter(f, fieldnames=FIELDS).writerows(rows)
            return len(rows)
        except PermissionError:
            print(f'[CSV LOCKED — close Excel] retry {attempt + 1}/{retries}')
            time.sleep(3)
    return 0


def safe_str(x):
    return '' if x is None else str(x).strip()


def find_vin(text):
    if not text:
        return ''
    m = VIN_RE.search(text.upper())
    return m.group(0) if m else ''


def format_phone(raw):
    if not raw:
        return ''
    digits = re.sub(r'[^\d]', '', raw)
    if not digits:
        return ''
    if digits.startswith('995') and len(digits) >= 11:
        return '+' + digits
    if len(digits) == 9 and digits[0] in '5739':
        return '+995' + digits
    if digits.startswith('7') and len(digits) == 11:
        return '+' + digits
    return '+' + digits


def to_int_str(x):
    try:
        return str(int(x)) if x is not None else ''
    except (ValueError, TypeError):
        return ''


def lookup(table, key, fallback):
    if not key:
        return ''
    return table.get(key) or fallback.get(key, '')


def build_description(item):
    parts = []
    raw = re.sub(r'\n{3,}', '\n\n', safe_str(item.get('car_desc')))
    if raw:
        parts.append(raw)
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
    flags = [label for k, label in flag_map.items() if item.get(k)]
    if flags:
        parts.append('ფუნქციები: ' + ', '.join(flags))
    if item.get('airbags'):
        parts.append(f'აირბაგები: {item["airbags"]}')
    return '\n\n'.join(parts)


def build_images(item):
    car_id = item.get('car_id')
    photo = item.get('photo', '')
    pic_n = item.get('pic_number') or 0
    if not (car_id and photo and pic_n):
        return []
    photo_ver = item.get('photo_ver', '')
    urls = []
    for i in range(1, min(int(pic_n), MAX_IMAGES) + 1):
        url = IMAGE_URL.format(photo=photo, car_id=car_id, n=i)
        if photo_ver:
            url += f'?v={photo_ver}'
        urls.append(url)
    return urls


def process_item(item, dicts):
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

    currency = CURRENCY_MAP.get(item.get('currency_id'), '')
    price = to_int_str(item.get('price'))

    engine_l = ''
    engine_cc = item.get('engine_volume')
    if engine_cc:
        try:
            engine_l = f'{int(engine_cc) / 1000:.1f}'
        except (ValueError, TypeError):
            pass

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
    images = build_images(item)

    catalyst = item.get('has_catalyst')
    row = {
        'ID':                 str(car_id),
        'Source':             'myauto',
        'Manufacturer':       man,
        'Model':              model,
        'Year':               to_int_str(item.get('prod_year')),
        'Body_Type':          lookup(dicts['category'], item.get('category_id'), CATEGORY_FB),
        'Price':              price,
        'Currency':           currency,
        'Price_With_Customs': '',
        'Engine_Volume_L':    engine_l,
        'Engine_Type':        lookup(dicts['fuel'], item.get('fuel_type_id'), FUEL_FB),
        'Cylinders':          to_int_str(item.get('cylinders')),
        'Has_Turbo':          'კი' if item.get('has_turbo') else '',
        'Power_HP':           to_int_str(item.get('hp')),
        'Gearbox':            lookup(dicts['gear'], item.get('gear_type_id'), GEAR_FB),
        'Drive_Wheels':       lookup(dicts['drive'], item.get('drive_type_id'), DRIVE_FB),
        'Mileage_KM':         mileage,
        'Color':              lookup(dicts['color'], item.get('color_id'), COLOR_FB),
        'Doors':              lookup(dicts['door'], item.get('door_type_id'), DOOR_FB),
        'Seats':              '',
        'Interior_Color':     lookup(dicts['saloon_color'], item.get('saloon_color_id'), COLOR_FB),
        'Interior_Material':  lookup(dicts['material'], item.get('saloon_material_id'), MATERIAL_FB),
        'Steering':           steering,
        'Condition':          '',
        'Customs_Cleared':    customs,
        'Has_Catalyst':       'კი' if catalyst == 1 else ('არა' if catalyst == 2 else ''),
        'Tech_Inspection':    'კი' if item.get('tech_inspection') else '',
        'VIN':                vin,
        'License_Plate':      safe_str(item.get('license_number')),
        'Location':           lookup(dicts['location'], item.get('location_id'), LOCATION_FB),
        'Seller_Name':        safe_str(item.get('client_name')),
        'Phone':              format_phone(safe_str(item.get('client_phone'))),
        'Posted_Date':        safe_str(item.get('order_date')),
        'Views':              to_int_str(item.get('views')),
        'URL':                CAR_URL.format(car_id=car_id),
        'Description':        build_description(item),
        'Video_1':            safe_str(item.get('video_url')),
    }
    for i in range(MAX_IMAGES):
        row[f'Image_{i + 1}'] = images[i] if i < len(images) else ''
    return row


async def block_handler(route):
    req = route.request
    if req.resource_type in {'image', 'media', 'font'}:
        await route.abort()
        return
    if any(d in req.url for d in BLOCK_DOMAINS):
        await route.abort()
        return
    await route.continue_()


async def fetch_page(page, page_num):
    event = asyncio.Event()
    result = []

    async def on_response(response):
        if API_HOST in response.url and API_PATH in response.url and not event.is_set():
            try:
                data = await response.json()
                result.append(data)
                event.set()
            except Exception:
                pass

    page.on('response', on_response)
    try:
        await page.goto(LIST_URL.format(page=page_num), wait_until='commit', timeout=PAGE_TIMEOUT)
        await asyncio.wait_for(event.wait(), timeout=API_WAIT)
        return result[0] if result else None
    except Exception:
        return None
    finally:
        page.remove_listener('response', on_response)


async def worker(context, queue, csv_lock, dicts, stats):
    page = await context.new_page()
    local_buf = []

    while True:
        try:
            page_num = queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        for attempt in range(3):
            try:
                data = await fetch_page(page, page_num)
                if data and data.get('statusCode') == 1:
                    for item in (data.get('data') or {}).get('items') or []:
                        try:
                            row = process_item(item, dicts)
                            if row:
                                local_buf.append(row)
                        except Exception:
                            pass
                    stats['done'] += 1
                    if stats['done'] % 50 == 0 or stats['done'] == stats['total']:
                        elapsed = time.time() - stats['start']
                        rate = stats['done'] / elapsed if elapsed else 0
                        eta = (stats['total'] - stats['done']) / rate if rate else 0
                        print(
                            f'[{stats["done"]}/{stats["total"]}] '
                            f'saved:{stats["saved"]} '
                            f'pages/s:{rate:.1f} '
                            f'ETA:{eta:.0f}s'
                        )
                    break
                elif attempt < 2:
                    await asyncio.sleep(2)
            except Exception as e:
                if attempt == 2:
                    stats['failed'] += 1
                    print(f'[FAIL page {page_num}] {e}')
                else:
                    await asyncio.sleep(1 + attempt)

        if len(local_buf) >= BATCH_FLUSH:
            async with csv_lock:
                stats['saved'] += append_batch(local_buf)
                local_buf.clear()

    if local_buf:
        async with csv_lock:
            stats['saved'] += append_batch(local_buf)

    await page.close()


async def main():
    print('Resetting MyAuto.csv...')
    reset_csv()
    start = time.time()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
            ],
        )
        auth = AUTH_FILE if os.path.exists(AUTH_FILE) else None
        if auth:
            print(f'Loading saved session from {AUTH_FILE}')
        else:
            print('No auth.json found — running without login (run login.py first if needed)')
        context = await browser.new_context(
            user_agent=USER_AGENT,
            locale='ka-GE',
            storage_state=auth,
        )
        await context.route('**/*', block_handler)

        print('Fetching page 1 to discover totals...')
        probe = await context.new_page()
        first_data = await fetch_page(probe, 1)
        await probe.close()

        if not first_data or first_data.get('statusCode') != 1:
            print('Could not get page 1 data — check connection or USER_AGENT. Exiting.')
            await browser.close()
            return

        meta = (first_data.get('data') or {}).get('meta') or {}
        total = meta.get('total', 0)
        last_page = meta.get('last_page', 0)
        print(f'Total cars: {total} | Pages: {last_page}')

        dicts = {
            'fuel': {}, 'gear': {}, 'drive': {}, 'color': {},
            'saloon_color': {}, 'location': {}, 'category': {}, 'door': {}, 'material': {},
        }

        first_rows = []
        for item in (first_data.get('data') or {}).get('items') or []:
            try:
                row = process_item(item, dicts)
                if row:
                    first_rows.append(row)
            except Exception:
                pass

        csv_lock = asyncio.Lock()
        stats = {'done': 1, 'total': last_page, 'saved': 0, 'failed': 0, 'start': start}

        async with csv_lock:
            stats['saved'] += append_batch(first_rows)

        queue = asyncio.Queue()
        for page_num in range(2, last_page + 1):
            queue.put_nowait(page_num)

        n_workers = min(CONCURRENT, max(1, last_page - 1))
        tasks = [
            asyncio.create_task(worker(context, queue, csv_lock, dicts, stats))
            for _ in range(n_workers)
        ]
        await asyncio.gather(*tasks)
        await browser.close()

    elapsed = time.time() - start
    print(f'Done. Saved {stats["saved"]} cars in {elapsed:.0f}s. Failed pages: {stats["failed"]}')


if __name__ == '__main__':
    asyncio.run(main())
