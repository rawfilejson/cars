# Deployment, step by step

How to get the project from local to production.

---

## The pieces

```
[ visitor ]
       |  HTTPS
[ Cloudflare Workers - static frontend (web/) ]
       |  HTTPS (fetch)
[ Render - FastAPI backend ]
       |
[ Supabase PostgreSQL  +  Cloudflare R2 (photos) ]

[ GitHub Actions ] -> cron 2x/day -> Playwright scraping -> Supabase + R2
```

Which file does what? the backend deploy is `render.yaml` plus `Dockerfile`, the
frontend is `wrangler.toml`, scraping is `.github/workflows/parse.yml` and the
photo backfill is `.github/workflows/sync_backfill.yml`.

---

## Secrets

No secret is stored in the repo. The same six values are needed in two places,
the Render dashboard and the GitHub Actions settings:

```
DATABASE_URL           postgresql://...   (Supabase connection string)
R2_ACCOUNT_ID          <cloudflare account id>
R2_ACCESS_KEY_ID       <r2 token key id>
R2_SECRET_ACCESS_KEY   <r2 token secret>
R2_BUCKET              cars-photos
R2_PUBLIC_URL          https://<your-bucket>.r2.dev
```

> Never write the real values into this file. If one ever leaks, rotate it - see `SECURITY.md`

---

## A. Backend on Render

1. Go to https://dashboard.render.com -> **New** -> **Web Service** and connect
   the `cars` repo.
2. Render picks up `render.yaml` automatically (docker runtime, Frankfurt,
   `/healthz` as the health check).
3. Under **Environment**, add the six secrets above. Anything marked
   `sync: false` in `render.yaml` has to be typed into the dashboard by hand.
4. Hit **Deploy**. The first build takes about five minutes.
5. Check it worked: `https://<your-app>.onrender.com/healthz` should return
   `{"status":"ok","db":true,...}`.

> On the free plan the service sleeps when idle, so the first request after a
> pause waits around 30 seconds for the cold start. The `starter` plan removes that.

If the backend URL changed, update it in `web/config.js`.

---

## B. Frontend on Cloudflare Workers

The frontend is just the static `web/` folder, served through Workers static
assets (`wrangler.toml`).

```powershell
npm install -g wrangler
wrangler login
wrangler deploy
```

`config.js` works out its own environment: on `localhost` it talks to the local
backend, anywhere else to the production Render URL. You only need to edit it if
that URL changes.

CORS: `allow_origins` in `src/api/main.py` has to include the frontend's real
origin. If you change domain, update it there and redeploy the backend.

---

## C. Scraping on GitHub Actions

1. Repo -> **Settings** -> **Secrets and variables** -> **Actions**, and add the
   same six secrets.
2. `parse.yml` runs the parsers plus `sync_photos` twice a day on a cron, after a
   random 0-60 minute delay.
3. To test by hand: **Actions** -> pick the workflow -> **Run workflow**.
4. To push a photo backlog through in one go: **Actions** -> **Photo Backfill** ->
   **Run workflow**, or `gh workflow run sync_backfill.yml`.

---

## Worth watching
- Render logs, for backend errors.
- The Supabase dashboard, for database size and connection limits.
- GitHub Actions history, for parser and backfill failures.
- Cloudflare Analytics, for traffic and bot requests.
