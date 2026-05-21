# car

Aggregated search for car listings from **autopapa.ge** and **myauto.ge** —
search by VIN, phone number, or free text. Free, no signup.

🇬🇪 [ქართული](#ქართულად) · 🇬🇧 [English](#english)

Live: <https://cars.demee-metreveli.workers.dev>

---

## English

### What this is

Two of the biggest car listing sites in Georgia (autopapa.ge and myauto.ge)
don't share data. If a car is up for sale on both, you can't easily search
across them. If someone calls you offering a car, looking up its history
means hunting through both sites manually.

This project scrapes both sites twice a day, normalizes the data into one
Postgres schema, and exposes a single search endpoint:

- **VIN** — full 17 characters or prefix
- **Phone** — any format (`+995555555555`, `995555555555`, `555555555`)
- **Free text** — trigram fuzzy search across descriptions

### Architecture

```
                                ┌──────────────────┐
                                │  Cloudflare      │
                                │  static Worker   │
                                │  (frontend)      │
                                └────────┬─────────┘
                                         │ fetch
                                         ▼
                                ┌──────────────────┐
                                │  Render          │
                                │  FastAPI         │
                                │  (backend)       │
                                └────────┬─────────┘
                                         │
                  ┌──────────────────────┼──────────────────────┐
                  ▼                      ▼                      ▼
         ┌──────────────┐       ┌──────────────┐       ┌──────────────┐
         │  Supabase    │       │  Cloudflare  │       │ GitHub       │
         │  PostgreSQL  │       │  R2 (photos) │       │ Actions      │
         │              │       │              │       │ (scheduled   │
         │              │       │              │       │  parser)     │
         └──────────────┘       └──────────────┘       └──────────────┘
```

### Layout

```
src/
├── common/
│   ├── config.py          Environment loading
│   ├── models.py          Car (pydantic)
│   ├── vin.py             VIN extraction + validation
│   ├── normalize.py       Phone, price, mileage cleanup
│   ├── anti_detection.py  Playwright + light stealth
│   ├── db.py              Postgres helpers (sync psycopg in threads)
│   ├── storage.py         R2 + local photo storage
│   └── runtime.py         Windows asyncio glue
├── parsers/
│   ├── autopapa.py        Playwright scraper for autopapa.ge
│   └── myauto.py          api2.myauto.ge JSON client
├── api/
│   ├── main.py            FastAPI app
│   ├── schemas.py         Request/response models
│   ├── search.py          VIN / phone / free-text endpoint
│   ├── stats.py           /stats endpoint
│   └── rate_limit.py      IP-based throttling
└── scripts/
    ├── init_db.py         Apply schema.sql
    ├── migrate_csv.py     Import legacy CSV dumps
    └── sync_photos.py     Download source photos → R2

web/
├── index.html             Frontend (no framework)
├── config.js              Frontend config (API base URL)
└── i18n.js                Translations dictionary (ka/en)
```

### Running locally

You need Python 3.12+, [uv](https://github.com/astral-sh/uv), and a running
Postgres instance (or use Docker: `docker compose up -d postgres`).

```bash
# Setup
uv sync
uv run playwright install chromium

# Config — copy and fill in real values
cp .env.example .env

# Initialize the database schema
uv run python -m src.scripts.init_db

# Scrape autopapa.ge once
uv run python -m src.parsers.autopapa

# Scrape myauto.ge once
uv run python -m src.parsers.myauto

# Run the API
uv run uvicorn src.api.main:app --port 8765 --reload

# Open frontend
cd web && python -m http.server 5500
# → http://localhost:5500
```

### Deployment

This repo runs on free tiers:
- Frontend: Cloudflare Workers static assets (`wrangler.toml`)
- Backend: Render web service (`render.yaml`, `Dockerfile`)
- Scheduled parser: GitHub Actions (`.github/workflows/parse.yml`)
- DB: Supabase Postgres
- Photo storage: Cloudflare R2

See `DEPLOY.md` for step-by-step.

### Security notes

See `SECURITY.md`. tl;dr: the search API is intentionally public and
anonymous; we throttle by IP. Database access is bypass-RLS via the
postgres role from the backend only.

### Contributing

Open issues and PRs welcome. The code style is intentionally close to
hand-written — terse comments, no over-engineering.

Contact: [@deme.brn](https://instagram.com/deme.brn)

### License

MIT.

---

## ქართულად

### რა არის ეს

autopapa.ge და myauto.ge საქართველოში მანქანების ორი ყველაზე დიდი საიტია,
მაგრამ მონაცემები ერთმანეთთან არ აქვთ გაზიარებული. თუ ერთი მანქანა ორივეზე
დევს, ვერ ეძებ ერთდროულად. თუ ვინმე გირეკავს მანქანის შესათავაზებლად, მისი
ისტორიის ნახვა ნიშნავს ორ საიტზე ცალცალკე ძიებას.

ეს პროექტი ორივე საიტს დღეში ორჯერ აპარსავს, მონაცემებს ნორმალიზებას უკეთებს
ერთ Postgres სქემაში და გვერდს უხსნის ერთიან ძიების ენდპოინტს:

- **VIN** — სრული 17 სიმბოლო ან თავსართი
- **ნომერი** — ნებისმიერი ფორმატი (`+995555555555`, `995555555555`, `555555555`)
- **თავისუფალი ტექსტი** — trigram-ით აღწერებში

### სად ვის უწევს ფული

ყველაფერი free tier-ზე ჯდება ჯერ-ჯერობით:
- Frontend: Cloudflare Workers (უფასო)
- Backend: Render (უფასო, 15წთ-ში იძინებს)
- DB: Supabase (500MB უფასოდ)
- R2 photo storage: 10GB უფასოდ
- GitHub Actions: 2000 წუთი/თვე უფასოდ

თუ პროექტი გაიზრდება, ხარჯი იქნება ~$30-40/თვე (Supabase Pro $25 + Render Starter $7).

### ლოკალურად გაშვება

დააინსტალირე Python 3.12+, [uv](https://github.com/astral-sh/uv),
და Postgres (ან Docker გამოიყენე):

```bash
uv sync
uv run playwright install chromium

cp .env.example .env
# შეავსე .env-ში DATABASE_URL, R2_* keys

uv run python -m src.scripts.init_db

uv run python -m src.parsers.autopapa     # ერთხელ ჩამოწიე autopapa
uv run python -m src.parsers.myauto       # ერთხელ ჩამოწიე myauto

uv run uvicorn src.api.main:app --port 8765 --reload
cd web && python -m http.server 5500       # → http://localhost:5500
```

### სტრუქტურა

ფაილების სქემა იხილე ზემოთ ინგლისურ ვერსიაში. სამი მთავარი ნაწილია:

1. **`src/parsers/`** — ცალცალკე scraper-ი თითო წყაროზე. AutoPapa-სთვის
   Playwright-ი (HTML scraping + VIN-ის ღილაკით გახსნა), MyAuto-სთვის
   პირდაპირ JSON API (`api2.myauto.ge`, რომ font-obfuscation აიცილოს).
2. **`src/api/`** — FastAPI backend ერთი `/search` endpoint-ით.
   მონაცემთა ბაზიდან კითხულობს, IP-ით ჭრის ლიმიტს (30/საათში).
3. **`web/`** — სტატიკური HTML + JS + Tailwind. ფრეიმვორქი არ აქვს —
   მინიმალურია სიჩქარისთვის.

### კონტრიბუცია

Issue-ები და PR-ები მისასალმებელია.

კონტაქტი: [@deme.brn](https://instagram.com/deme.brn)

### ლიცენზია

MIT.
