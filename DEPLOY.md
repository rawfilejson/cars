# Deployment სახელმძღვანელო — ნაბიჯ ნაბიჯ

ეს დოკუმენტი აღწერს როგორ გავიყვანოთ პროექტი ლოკალურიდან production-ში.

---

## სტრუქტურა

```
[ მომხმარებელი ]
       ↓ HTTPS
[ Cloudflare Pages — frontend (web/index.html) ]
       ↓ HTTPS
[ Fly.io — backend FastAPI ]
       ↓
[ Supabase PostgreSQL + Cloudflare R2 ]

[ GitHub Actions ] → cron 2x/day → Playwright scraping → Supabase + R2
```

---

## Pre-deploy checklist

ეხლა აუცილებლად გააკეთე **სანამ deploy-ს გავუშვებთ:**

- [ ] **Supabase Pro tier** — დახარჯე $25/თვე (იქ ხდება automatic backup, 8GB DB)
- [ ] **Secrets rotate** (იხ. SECURITY.md):
  - [ ] DB password — Supabase Dashboard → Settings → Database → Reset password
  - [ ] JWT secret — Settings → API → Reset JWT secret
  - [ ] R2 API token — Cloudflare → R2 → Tokens → წაშალე ძველი, შექმენი ახალი
- [ ] `.env`-ში ჩაანაცვლე ახალი secrets
- [ ] OAuth consent screen-ში App name დააფიქსირე (Google Cloud Console)
- [ ] MyAuto migration შეასრულე (`python -m src.scripts.migrate_csv --file MyAuto.csv --source myauto`)

---

## E. Backend → Fly.io

### E1. Install flyctl

PowerShell-ში:
```powershell
iwr https://fly.io/install.ps1 -useb | iex
```

(Mac/Linux: `curl -L https://fly.io/install.sh | sh`)

### E2. Sign up + login
```powershell
flyctl auth signup
# ან თუ უკვე გაქვს:
flyctl auth login
```

### E3. App-ის შექმნა + first deploy
```powershell
cd C:\Users\deme\Documents\GitHub\cars
flyctl launch --copy-config --name cars-api-deme --region fra --no-deploy
```

`--name cars-api-deme` — ცვალე უნიკალურად (Fly.io გლობალურად უნიკალური უნდა იყოს).

### E4. Secrets-ის ჩასმა
```powershell
flyctl secrets set `
  DATABASE_URL="postgresql://postgres.xjoskipwvbofwgkupegw:NEW_PASSWORD@aws-1-eu-central-1.pooler.supabase.com:5432/postgres" `
  SUPABASE_JWT_SECRET="NEW_JWT_SECRET" `
  SUPABASE_URL="https://xjoskipwvbofwgkupegw.supabase.co" `
  SUPABASE_ANON_KEY="sb_publishable_..." `
  SUPABASE_SERVICE_ROLE_KEY="sb_secret_..." `
  R2_ACCOUNT_ID="500172016ca6d47829a171c320557233" `
  R2_ACCESS_KEY_ID="NEW_KEY_ID" `
  R2_SECRET_ACCESS_KEY="NEW_SECRET" `
  R2_BUCKET="cars-photos" `
  R2_PUBLIC_URL="https://pub-5a5cb99bc7d2485faf5937207b078a27.r2.dev"
```

### E5. Deploy
```powershell
flyctl deploy
```

5-10 წუთი დარჩება docker image-ის build-ისთვის.

### E6. ვერიფიკაცია
```powershell
flyctl status
flyctl logs
# Health check
curl https://cars-api-deme.fly.dev/healthz
```

ბექენდის URL: `https://cars-api-deme.fly.dev`

---

## F. Frontend → Cloudflare Pages

### F1. Repo უკვე GitHub-ში უნდა იყოს

(იხ. Step D რომელიც გავაკეთეთ წინა-შემდეგ)

### F2. Cloudflare Pages-ში connect
1. https://dash.cloudflare.com → Workers & Pages
2. **Create application** → **Pages** → **Connect to Git**
3. დაუკავშირდი GitHub-ს, აარჩიე `cars` repo
4. Build configuration:
   - **Framework preset**: None
   - **Build command**: (ცარიელი)
   - **Build output directory**: `web`
5. **Environment variables** არ ვამატებთ (config.js-ში ხელით ვინახავთ ჯერ)
6. **Save and Deploy**

URL იქნება: `https://cars-<random>.pages.dev`

### F3. config.js production-ისთვის
GitHub-ში დაკომიტე `web/config.js` ფაილი production URL-ით:

```js
window.SUPABASE_URL      = 'https://xjoskipwvbofwgkupegw.supabase.co';
window.SUPABASE_ANON_KEY = 'sb_publishable_...';
window.API_BASE          = 'https://cars-api-deme.fly.dev';
```

Push → Cloudflare ავტომატურად re-deploy-ი.

### F4. Backend CORS-ში დაამატე frontend domain

`src/api/main.py`-ში allow_origins-ში დაამატე `https://cars-<random>.pages.dev`, შემდეგ:

```powershell
flyctl deploy
```

### F5. Custom domain (არასავალდებულო)

თუ ცარიელი domain გექნება:
- Cloudflare Pages → Settings → Custom domains → Add
- DNS რეგისტრატორში CNAME → `<your-domain>.com` → `<pages-url>.pages.dev`

---

## G. GitHub Actions scheduled parser

### G1. Secrets repo-ში
GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

დაამატე ერთი-ერთი:
- `DATABASE_URL`
- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`
- `R2_PUBLIC_URL`

### G2. Workflow ჩართე
`.github/workflows/parse.yml` უკვე გვაქვს. პირველი push-ის შემდეგ GitHub Actions ავტომატურად დაიწყებს cron-ის ჩამოყრას (03:00 და 15:00 UTC).

### G3. Manual trigger ტესტისთვის
- GitHub repo → **Actions** → **Scheduled Parser** workflow → **Run workflow**

---

## Production-ის შემდეგი ნაბიჯები

### თვის ბოლოს / პერიოდულად:
- `flyctl logs` — შეცდომების მონიტორინგი
- Supabase Dashboard — DB size / connection limits
- Cloudflare → Analytics — traffic patterns / saljali bot requests
- GitHub Actions history — parser failures

### ფასების მონიტორინგი:
- Supabase Pro: $25/თვე (fixed)
- Fly.io: ~$2-5/თვე (cars-api იძინებს როცა traffic-ი არ არის)
- Cloudflare Pages: უფასო
- Cloudflare R2: ~$0.15/GB/თვე storage, free egress
- ჯამში: ~$30-40/თვე

### Subscription-ის შემოსავალი 10 ლარით (3.7 USD):
- 10 paying user = ~$37/თვე → ფარავს infra-ს
- 20 → $74/თვე → profit
- 100 → $370/თვე
