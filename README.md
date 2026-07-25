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

This project scrapes both sites twice a day, normalizes everything into one
Postgres table, and serves a single search endpoint that accepts:

- **VIN** — full 17 characters or a prefix
- **Phone** — any format (`+995555555555`, `995555555555`, `555555555`)
- **Free text** — fuzzy search across make, model, description and location
- **Filters only** — browse mode (e.g. all 2018–2022 cars under $20k)

---

## How it works, step by step

The whole system is four moving parts: **scrapers** put listings into
Postgres, a **photo sync** copies images to object storage, a **FastAPI**
backend answers searches, and a **static frontend** talks to that backend.
Scheduled jobs on GitHub Actions keep it all running.

```
   autopapa.ge          myauto.ge
        │                   │
   (Playwright)     (JSON API client)
        │                   │
        └────────┬──────────┘
                 ▼
        src/parsers/*.py            1. scrape
                 │
                 ▼
     normalize → Car model          2. clean up
                 │
                 ▼
        Postgres `cars` table       3. upsert
                 │        │
                 │        └──────►  sync_photos → Cloudflare R2   4. photos
                 ▼
         FastAPI /search            5. query
                 │
                 ▼
        web/index.html              6. render
```

### 1. Scraping

Each source has its own parser in `src/parsers/`, because the two sites need
completely different approaches:

- **`myauto.py`** talks to `api2.myauto.ge/ka/products` directly and reads
  JSON. The public HTML site obfuscates prices and phone numbers with a
  custom font, so parsing the rendered page would give you garbage digits —
  the JSON API returns clean values. Product IDs are cached in
  `exports/myauto-ids.json` so repeat runs can skip work.

- **`autopapa.py`** has no usable API, so it drives a headless Chromium
  through Playwright. `src/common/anti_detection.py` sets up a lightly
  disguised browser context (realistic user-agent, no obvious automation
  flags). The scraper walks the listing pages, opens each car, and clicks the
  "show VIN" button, since the VIN isn't in the initial HTML.

Both parsers are async and scrape several pages concurrently
(`CONCURRENT_PAGES`). `src/common/robots.py` keeps the crawl polite.

### 2. Normalizing

Raw scraped values are messy, so everything is funnelled through one shape —
the `Car` model in `src/common/models.py` — before it goes near the database:

- `src/common/normalize.py` — phone numbers into a canonical form, prices
  into an integer plus a currency, mileage into kilometres, and free-text
  fields into consistent casing.
- `src/common/vin.py` — pulls a VIN out of the description when the
  structured field is empty, and validates it (17 characters, no `I`/`O`/`Q`).

This is why searching works across sources: a phone number written five
different ways on two sites ends up identical in the database.

### 3. Storing

`src/common/db.py` upserts into a single `cars` table. The key detail is the
unique constraint:

```sql
CONSTRAINT cars_source_id_unique UNIQUE (source, source_id)
```

Re-scraping a listing **updates** it instead of creating a duplicate, and a
trigger bumps `updated_at` on every write. That timestamp is what the prune
job later uses to find stale listings.

The table also has a generated column that makes free-text search cheap:

```sql
search_blob TEXT GENERATED ALWAYS AS (
    lower(manufacturer || ' ' || model || ' ' || description || ' ' || ...)
) STORED
```

Postgres maintains it automatically on every insert and update, and a GIN
trigram index sits on top of it.

### 4. Photos

Scrapers only record the source CDN URLs in `image_urls`. Those URLs rot and
often block hotlinking, so `src/scripts/sync_photos.py` downloads each photo
and re-uploads it to Cloudflare R2 under a stable key:

```
{source}/{source_id}/{index}.jpg
```

The keys land in `image_keys`, and the API hands the frontend absolute URLs
built from `R2_PUBLIC_URL`. The job only picks rows that still have no
`image_keys`, so it is resumable — it can be stopped and restarted freely.
With `--purge-local` it streams straight to R2 without keeping a local copy,
which is how it runs in CI.

### 5. Searching

There is one main endpoint, `POST /search`, and it works out what you meant
rather than making you choose. `_smart_route()` in `src/api/search.py` checks
the query in this order:

1. **VIN** — 17 valid VIN characters → exact match on the indexed `vin`
   column.
2. **Phone** — mostly digits → matches on digits only:
   `regexp_replace(phone, '\D', '', 'g') LIKE '%suffix'`. A leading wildcard
   normally forces a full table scan, so there is a trigram GIN index on
   exactly that expression to keep it fast.
3. **Free text** — every word must appear in `search_blob`, then results are
   ordered by trigram `similarity()` against the make/model/year blob, so the
   closest titles come first.
4. **Filters only** — no text at all → browse mode, ordered by your chosen
   sort.

Filters (year, price, mileage, manufacturer, model, body, fuel, gearbox,
drive, location, customs) apply to free-text and browse queries. They are
deliberately ignored for VIN and phone lookups, which are exact by nature.
Prices are converted to USD in SQL before any range comparison, so a mix of
currencies still sorts correctly.

Supporting endpoints: `/search/count` (drives the live result counter on the
search button), plus `/makes`, `/facets` and `/stats`, which are cached
hourly because they change rarely and are expensive to compute.

### 6. Rate limiting

The site is anonymous, so there is no account to limit. Limiting purely by IP
punishes shared connections — home Wi-Fi and mobile CGNAT put many people
behind one address. So `src/api/rate_limit.py` uses two identities:

- **Primary:** an anonymous token the browser generates and keeps in
  `localStorage`, sent as `X-Client-Id`. Two people on the same network no
  longer eat each other's quota.
- **Backstop:** the IP address, which exists only to stop someone rotating
  tokens to scrape the whole database.

There's a short cooldown between searches, an hourly per-token limit, and an
hourly per-IP ceiling. All timing is measured with the database's `NOW()`,
never the client's clock. The real client IP comes from `CF-Connecting-IP`,
which is trustworthy because the origin is only reachable through Cloudflare
and Cloudflare overwrites any forged value.

### 7. Frontend

`web/index.html` is the entire app — one file, no framework, no build step,
with the CSS and JS inline. It's served as a static asset, so it loads fast
and costs nothing to host.

- `web/i18n.js` — all UI strings in Georgian, English, Russian and Kazakh.
- `web/config.js` — picks the API base URL (localhost in dev, Render in prod).

Every `<select>` is wrapped by a small custom dropdown component that renders
checkboxes, group headers and brand logos while keeping the native element as
the source of truth. All multi-selects start with **everything checked**,
which means "no filter" — you narrow by unchecking, or clear all and pick a
few. None-selected and all-selected both collapse to sending nothing.

Saved cars, saved searches, recent history and the comparison tray all live
in `localStorage`, so there are no accounts and nothing personal on the
server.

### 8. Scheduled jobs

Everything runs on GitHub Actions (`.github/workflows/`):

| Workflow | Schedule | What it does |
|---|---|---|
| `parse.yml` | twice a day | Runs both parsers, then syncs photos. Waits a random delay first so requests don't arrive on a robotic schedule. |
| `prune.yml` | daily | Deletes listings that are genuinely gone. |
| `sync_backfill.yml` | every 6 hours | Works through any photo backlog. |
| `backfill_blitz.yml` | manual | Same as above but in 3 parallel shards, to clear a large backlog in one go. |

The prune job is deliberately careful: a listing is only a *candidate* when
nothing has touched it for `--days`, and every candidate is then re-checked
against the source. Only listings the source confirms are gone get deleted —
an old `updated_at` alone never deletes anything, because the scrapers skip
listings that already look unchanged.

---

### Layout

```
src/
├── common/
│   ├── config.py          Environment loading
│   ├── models.py          Car model
│   ├── vin.py             VIN extraction + validation
│   ├── normalize.py       Phone, price, mileage cleanup
│   ├── anti_detection.py  Playwright + light stealth
│   ├── robots.py          Crawl politeness
│   ├── db.py              Postgres helpers
│   ├── storage.py         R2 + local photo storage
│   └── runtime.py         Windows asyncio glue
├── parsers/
│   ├── autopapa.py        Playwright scraper for autopapa.ge
│   └── myauto.py          api2.myauto.ge JSON client
├── api/
│   ├── main.py            FastAPI app
│   ├── schemas.py         Request/response models
│   ├── search.py          Search routing, filters, pagination
│   ├── makes.py           Manufacturer → models
│   ├── facets.py          Filter values
│   ├── stats.py           Totals
│   ├── rate_limit.py      Token + IP throttling
│   └── db_pool.py         Connection pool
└── scripts/
    ├── init_db.py         Apply schema.sql
    ├── migrate_csv.py     Import legacy CSV dumps
    └── sync_photos.py     Download source photos → R2

db/schema.sql              Tables, indexes, triggers
scripts/prune_dead.py      Verify and remove dead listings

web/
├── index.html             Frontend (no framework)
├── config.js              API base URL
└── i18n.js                Translations (ka/en/ru/kk)
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

# Scrape once (either or both)
uv run python -m src.parsers.autopapa
uv run python -m src.parsers.myauto

# Copy photos to R2 (needs the R2_* variables)
uv run python -m src.scripts.sync_photos

# Run the API
uv run uvicorn src.api.main:app --port 8765 --reload

# Serve the frontend
cd web && python -m http.server 5500
# → http://localhost:5500
```

Run the tests with `uv run pytest -q`.

### Deployment

This repo runs on free tiers:

- Frontend: Cloudflare Workers static assets (`wrangler.toml`)
- Backend: Render web service (`render.yaml`, `Dockerfile`)
- Scheduled jobs: GitHub Actions (`.github/workflows/`)
- Database: Supabase Postgres
- Photo storage: Cloudflare R2

See `DEPLOY.md` for step-by-step instructions.

### Security notes

See `SECURITY.md`. In short: the search API is intentionally public and
anonymous, throttled per browser token with an IP ceiling behind it. The
backend connects with an owner role that bypasses RLS, and Supabase's
anonymous REST access is disabled.

### Contributing

Issues and PRs welcome. The code style is intentionally plain — terse
comments, no over-engineering.

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
ერთ Postgres ცხრილში და ხსნის ერთიან ძიების ენდპოინტს:

- **VIN** — სრული 17 სიმბოლო ან თავსართი
- **ნომერი** — ნებისმიერი ფორმატი (`+995555555555`, `995555555555`, `555555555`)
- **თავისუფალი ტექსტი** — მწარმოებელი, მოდელი, აღწერა, ლოკაცია
- **მხოლოდ ფილტრები** — დათვალიერება (მაგ. 2018–2022, $20k-მდე)

### როგორ მუშაობს — ნაბიჯ-ნაბიჯ

1. **პარსინგი.** თითო წყაროს თავისი პარსერი აქვს `src/parsers/`-ში.
   MyAuto-სთვის პირდაპირ JSON API (`api2.myauto.ge`) — HTML-ზე ფასები და
   ნომრები შრიფტითაა დაფარული, JSON კი სუფთა მნიშვნელობებს აბრუნებს.
   AutoPapa-ს API არ აქვს, ამიტომ Playwright-ით headless Chromium დადის
   გვერდებზე და VIN-ის ღილაკს ხსნის.

2. **ნორმალიზაცია.** `normalize.py` ასწორებს ნომერს, ფასს და გარბენს,
   `vin.py` აღწერიდან VIN-ს იღებს და ამოწმებს. ყველაფერი ერთ `Car` მოდელში
   ჯდება — ამიტომ მუშაობს ძიება ორივე წყაროზე ერთდროულად.

3. **შენახვა.** `(source, source_id)` unique constraint-ის წყალობით ხელახალი
   პარსინგი დუბლიკატს არ ქმნის, არამედ განაახლებს. `search_blob` გენერირებული
   სვეტია, რომელზეც trigram ინდექსი დგას.

4. **ფოტოები.** `sync_photos.py` წყაროს ფოტოებს ჩამოტვირთავს და Cloudflare
   R2-ში დებს `{source}/{source_id}/{index}.jpg` გასაღებით. resumable-ია —
   მხოლოდ იმ ჩანაწერებს ირჩევს, რომლებსაც ჯერ არ აქვს `image_keys`.

5. **ძიება.** `POST /search` თვითონ ცნობს რა ჩაწერე: VIN (ზუსტი დამთხვევა) →
   ნომერი (მხოლოდ ციფრებზე, trigram ინდექსით) → თავისუფალი ტექსტი
   (`search_blob` + similarity რანჟირება) → მხოლოდ ფილტრები. ფასები SQL-ში
   დოლარში გადაჰყავს, რომ სხვადასხვა ვალუტა სწორად შედარდეს.

6. **ლიმიტი.** ავტორიზაცია არ გვაქვს, ამიტომ მთავარი იდენტობა ბრაუზერის
   ანონიმური token-ია (`X-Client-Id`), IP მხოლოდ backstop-ია — ერთ WiFi-ზე
   ორი ადამიანი ერთმანეთს ლიმიტს აღარ ჭამს.

7. **ფრონტი.** `web/index.html` — ერთი ფაილი, ფრეიმვორქის და build-ის
   გარეშე. ყველა ფილტრში ნაგულისხმევად ყველაფერი მონიშნულია (= ფილტრი არ
   არის); ვიწროვდები მონიშვნის მოხსნით. შენახული მანქანები, ძიებები და
   შედარება localStorage-შია — სერვერზე პირადი არაფერი ინახება.

8. **ავტომატიზაცია.** GitHub Actions: `parse.yml` (დღეში 2-ჯერ),
   `prune.yml` (დღეში ერთხელ, შლის მხოლოდ იმას, რასაც წყარო დაადასტურებს რომ
   აღარ არსებობს), `sync_backfill.yml` (ფოტოების backlog).

### სად ვის უწევს ფული

- Frontend: Cloudflare Workers (უფასო)
- Backend: Render (უფასო, 15წთ-ში იძინებს)
- DB: Supabase (500MB უფასოდ)
- R2 photo storage: 10GB უფასოდ
- GitHub Actions: public repo-ზე შეუზღუდავი

### ლოკალურად გაშვება

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

ტესტები: `uv run pytest -q`

### კონტრიბუცია

Issue-ები და PR-ები მისასალმებელია.

კონტაქტი: [@deme.brn](https://instagram.com/deme.brn)

### ლიცენზია

MIT.
