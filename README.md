# cars — ქართული მანქანების მონაცემთა ბაზა

პროექტი: autopapa.ge და myauto.ge საიტებიდან მანქანების ინფორმაციის ამოღება,
სტრუქტურირებულ PostgreSQL ბაზაში შენახვა და მერე ვებსაიტის წინიდან მათი ძიება
(VIN-ით, ნომრით, თავისუფალი ტექსტით).

## სტრუქტურა

```
cars/
├── db/
│   └── schema.sql              # PostgreSQL ცხრილების სქემა
├── docker-compose.yml          # ლოკალური Postgres
├── pyproject.toml              # dependencies
├── .env.example                # კონფიგის შაბლონი (.env-ად დააკოპირე)
├── .gitignore
└── src/
    ├── common/
    │   ├── config.py           # .env-დან კონფიგის წაკითხვა
    │   ├── models.py           # Car (Pydantic) — მონაცემთა ფორმა
    │   ├── vin.py              # VIN-ის ამოღება / ვალიდაცია
    │   ├── normalize.py        # ფასი, ნომერი, გარბენი — გასუფთავება
    │   ├── anti_detection.py   # Playwright stealth + რესურსების ფილტრი
    │   ├── db.py               # PostgreSQL helpers (upsert_cars და სხვ.)
    │   └── storage.py          # ფოტოები: ლოკალური + Cloudflare R2
    ├── parsers/
    │   └── autopapa.py         # autopapa.ge პარსერი
    └── scripts/
        ├── init_db.py          # სქემის გაშვება (თუ Docker არ იყენებ)
        ├── migrate_csv.py      # ძველი CSV → DB
        └── sync_photos.py      # ფოტოების ჩამოტვირთვა + R2
```

## ერთჯერადი setup

### 1. dependencies-ის დაყენება

```powershell
# uv-ით (პროექტი ამისთვისაა მორგებული)
uv sync

# ან pip-ით
pip install -e .

# Playwright-ის ბრაუზერი
playwright install chromium
```

### 2. PostgreSQL — Docker-ით (ყველაზე მარტივი)

ერთი ბრძანება და გექნება PostgreSQL ცხრილებით:

```powershell
docker compose up -d
```

თუ Docker არ გაქვს, დააინსტალირე ლოკალურად Postgres და გაუშვი:

```powershell
python -m src.scripts.init_db
```

### 3. .env ფაილის შექმნა

```powershell
copy .env.example .env
```

გახსენი `.env` და შეცვალე:

- `DATABASE_URL` — საჭიროა, თუ Docker-ის ნაცვლად სხვაგან გაქვს Postgres
- `R2_*` ცვლადები — როცა Cloudflare R2 account გექნება (აქ ჯერ შეიძლება ცარიელი დარჩეს)
- `PROXY_URL` — თუ პროქსი გექნება (არასავალდებულო)

### 4. Cloudflare R2-ის შექმნა (როცა მზად იქნები)

1. გახსენი https://dash.cloudflare.com → R2
2. შექმენი ახალი bucket: `cars-photos`
3. „Manage R2 API tokens" → „Create API token" → Read & Write
4. დააკოპირე `Account ID`, `Access Key ID`, `Secret Access Key`
5. ჩაწერე `.env`-ში
6. bucket-ის Settings → „Public access" → დაამატე custom domain ან გამოიყენე `pub-xxx.r2.dev` URL
7. `R2_PUBLIC_URL` ცვლადს მიენიჭე ეს URL

## ყოველდღიური გამოყენება

### პარსერის გაშვება

```powershell
python -m src.parsers.autopapa
```

რა ხდება:

1. იხსნება headless ბრაუზერი stealth-ის რეჟიმში
2. იღებს ყველა საძიებო გვერდის ლინკებს
3. ბაზაში ამოწმებს რომელია უკვე — ეგენი გამოტოვებს
4. ერთდროულად ხსნის რამდენიმე ფურცელს და ამოწერს ყველაფერს
5. ბაზაში ჩაწერა batch-ად — სიჩქარისთვის

დაჯდინება: `.env`-ში `CONCURRENT_PAGES` — დააფიხსირე რამდენ ფურცელს ხსნის ერთად.

### ფოტოების სინქი

```powershell
# ყველა მანქანის ფოტოები (რომელთა ჯერ არ მოგვიტანია)
python -m src.scripts.sync_photos

# მხოლოდ autopapa-დან, 100 ცალი
python -m src.scripts.sync_photos --source autopapa --limit 100

# მხოლოდ ლოკალურად, R2-ში ნუ ატვირთავ
python -m src.scripts.sync_photos --local-only
```

ფაილების სტრუქტურა:
```
photos/
├── autopapa/
│   └── 905889/
│       ├── 1.jpg
│       ├── 2.jpg
│       └── ...
└── myauto/
    └── 121480968/
        ├── 1.jpg
        └── ...
```

R2-ში იგივე გასაღებებითაა.

### ძველი CSV-დან მიგრაცია

გვაქვს ორი ფაილი (AutoPapa.csv და MyAuto.csv) — გადავიყვანოთ ბაზაში:

```powershell
python -m src.scripts.migrate_csv --file AutoPapa.csv --source autopapa
python -m src.scripts.migrate_csv --file MyAuto.csv --source myauto
```

შემდეგ ფოტოები:

```powershell
python -m src.scripts.sync_photos
```

და ბოლოს — ცოცხალი პარსერი დარჩენილი/ახალი მონაცემებისთვის:

```powershell
python -m src.parsers.autopapa
```

## ნიუანსები

### VIN-ის ლოგიკა

- ჯერ ცდილობს ღილაკით (autopapa-ს popup-ი)
- მერე — აღწერაში (regex-ით, case-insensitive)
- ბოლოს — AJAX endpoint-ით
- მასკირებული ვინი (KMHL34*****) — გამოტოვებულია
- ბაზაში ყოველთვის დიდი ასოებით ინახება
- თუ ვერ ვიპოვით — დარჩება ცარიელი (და ეს ნორმალურია)

### ნომრების ფორმატი

- ყოველთვის `+`-ით იწყება
- ქართული 9-ციფრიანი ნომერი → `+995` ემატება ავტომატურად
- რუსული 11-ციფრიანი 7-ით იწყება → `+` ემატება წინ

### განბაჟება

ბაზაში PostgreSQL boolean-ად ინახება (`true`/`false`/`null`).

### Resume

თუ შუა გზაზე ჩავარდა — უბრალოდ ხელახლა გაუშვი. ID-ით ვამოწმებთ ბაზაში
უკვე არსებულ მანქანებს და მათ გამოვტოვებთ.

## უსაფრთხოება (ვებსაიტისთვის — მომავალში)

> ⚠️ მნიშვნელოვანი: „აბსოლუტურად დაცული ყველა გატეხვისგან" — შეუძლებელია.
> ნებისმიერი სისტემა შეიძლება გაიტეხოს. რეალურად ვითხოვთ „გონივრულად დაცული"
> და ხშირი audit-ი.

რა გავაკეთებთ ვებსაიტისთვის როცა იქამდე მივალთ:

1. **SQL injection** — psycopg-ით პარამეტრიზებული queries ვიყენებთ (უკვე).
2. **HTTPS** — Cloudflare-ით (Let's Encrypt-ით უფასოა).
3. **Rate limiting** — Cloudflare WAF + application-level rate limit.
4. **Secrets** — `.env`-ში, არასოდეს კოდში, არასოდეს git-ში.
5. **CSRF** — POST endpoints-ისთვის CSRF token.
6. **Input validation** — Pydantic schemas-ით ყველა user input.
7. **Logging** — წარუმატებელი login-ები, საეჭვო search-ები.
8. **DB user-ის უფლებები** — ვებსაიტის user-ი მხოლოდ SELECT + INSERT searches-ში.
9. **Payment-ის ვერიფიკაცია** — payment status სერვერ-სერვერ webhook-ით (არ ვენდობით client-ს).
10. **Audit ლოგი** — ვისი როდის როგორი ძიება, რა შედეგი.

## პრობლემები რომ შეგხვდეს

**autopapa CSV-ში ნომრები გადადგა `9.96E+11` ფორმაში** — Excel-მა გადააქცია
სამეცნიერო ნოტაციად. რომ ეს არ მოხდეს, CSV-ს არ ხსნი Excel-ში — გამოიყენე
LibreOffice ან VS Code. ბაზაში text-ად ვინახავთ — ეს ფაქტი არ მოგვაშავა.

**Playwright-ი ვერ ხსნის ბრაუზერს** — `playwright install chromium`

**PostgreSQL უარს ამბობს კავშირზე** — შეამოწმე `docker ps`, კონტეინერი მუშაობს?
ან შეცვალე `DATABASE_URL` `.env`-ში.

**„VIN ცარიელია" ბევრ მანქანაზე** — ეს ნორმალურია. ბევრი გამყიდველი VIN-ს არ
აქვეყნებს. ჩვენი ლოგიკა ცდილობს მაქსიმუმს, მაგრამ თუ ვერ იპოვი — ცარიელი
რჩება.
