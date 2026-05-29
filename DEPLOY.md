# Deployment — ნაბიჯ ნაბიჯ

როგორ გავიყვანოთ პროექტი ლოკალურიდან production-ში. საიტი ანონიმური და უფასოა —
ავტორიზაცია/გადახდა არ არის.

---

## სტრუქტურა

```
[ მომხმარებელი ]
       ↓ HTTPS
[ Cloudflare Workers — static frontend (web/) ]
       ↓ HTTPS (fetch)
[ Render — FastAPI backend ]
       ↓
[ Supabase PostgreSQL  +  Cloudflare R2 (ფოტოები) ]

[ GitHub Actions ] → cron 2x/day → Playwright scraping → Supabase + R2
```

ფაილები: backend deploy — `render.yaml` + `Dockerfile`; frontend — `wrangler.toml`;
scraping — `.github/workflows/parse.yml`; backfill — `.github/workflows/sync_backfill.yml`.

---

## Secrets

repo-ში secret არ ინახება. ერთი და იგივე 6 მნიშვნელობა გვჭირდება ორ ადგილას
(Render-ისა და GitHub Actions-ის dashboard-ებში):

```
DATABASE_URL           postgresql://...   (Supabase connection string)
R2_ACCOUNT_ID          <cloudflare account id>
R2_ACCESS_KEY_ID       <r2 token key id>
R2_SECRET_ACCESS_KEY   <r2 token secret>
R2_BUCKET              cars-photos
R2_PUBLIC_URL          https://<your-bucket>.r2.dev
```

> ⚠️ ნამდვილი მნიშვნელობები ამ ფაილში არ იწერება. თუ რომელიმე ოდესმე გასაჟონა,
> აუცილებლად დაარესეტე (იხ. `SECURITY.md`).

---

## A. Backend → Render

1. https://dashboard.render.com → **New** → **Web Service** → connect GitHub repo `cars`.
2. Render წაიკითხავს `render.yaml`-ს ავტომატურად (docker runtime, frankfurt, `/healthz` health check).
3. **Environment** → დაამატე ზემოთ ჩამოთვლილი 6 secret (`render.yaml`-ში `sync: false`-ით
   მონიშნულები dashboard-ში ხელით იწერება).
4. **Deploy**. პირველი build ~5 წუთი.
5. ვერიფიკაცია: `https://<your-app>.onrender.com/healthz` → `{"status":"ok","db":true,...}`.

> free plan-ზე სერვისი უმოქმედობის შემდეგ "იძინებს" — პირველი request ~30წმ-ს ელოდება (cold start).
> ამის მოსაშორებლად: plan → `starter` ($7/თვე).

ბექენდის URL ჩაწერე `web/config.js`-ში (production ფილიალში) თუ ის შეიცვალა.

---

## B. Frontend → Cloudflare Workers

frontend არის სტატიკური `web/` ფოლდერი, Workers static-assets-ით (`wrangler.toml`).

```powershell
npm install -g wrangler
wrangler login
wrangler deploy
```

`config.js` თავად ცნობს გარემოს: `localhost`-ზე ლოკალურ backend-ს იყენებს, სხვაგან —
production Render URL-ს. ხელით რედაქტირება არ სჭირდება, თუ URL იგივეა.

CORS: backend-ის `src/api/main.py`-ში `allow_origins` უნდა შეიცავდეს frontend-ის
ნამდვილ origin-ს. domain-ის შეცვლისას განაახლე და ხელახლა deploy.

---

## C. Scraping → GitHub Actions

1. repo → **Settings** → **Secrets and variables** → **Actions** → დაამატე ზემოთ ჩამოთვლილი 6 secret.
2. `parse.yml` cron-ით დღეში 2-ჯერ უშვებს parser-ს + `sync_photos`-ს (შემთხვევითი 0-60წთ delay-ით).
3. ხელით ტესტი: **Actions** → აირჩიე workflow → **Run workflow**.
4. ფოტოების backlog-ის ერთჯერადი ატვირთვა: **Actions** → **Photo Backfill** → **Run workflow**
   (ან `gh workflow run sync_backfill.yml`).

---

## ხარჯები (free-tier რეალობა)

| სერვისი | Free | ფასიანი |
|---------|------|---------|
| Render | ✅ (cold start) | starter $7/თვე — cold start გარეშე |
| Cloudflare Workers | ✅ | — |
| Supabase | ✅ (auto-backup გარეშე) | Pro $25/თვე — auto-backup + მეტი ადგილი |
| Cloudflare R2 | ✅ 10GB storage, free egress | ~$0.015/GB/თვე ზევით |
| GitHub Actions | ✅ 2000 წთ/თვე | — |

---

## პერიოდული მონიტორინგი
- Render logs — backend შეცდომები.
- Supabase Dashboard — DB ზომა / connection limits.
- GitHub Actions history — parser/backfill failures.
- Cloudflare Analytics — traffic / bot requests.
