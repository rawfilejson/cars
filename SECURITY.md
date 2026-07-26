# Security

> Nothing is "completely secure". The goal here is sensibly secure, with a small
> attack surface.

The site is **anonymous and free**: no accounts, no payments, no personal data
collected. That removes a lot of risk before any code is written.

Architecture: Cloudflare Workers (static frontend) -> Render (FastAPI backend)
-> Supabase PostgreSQL + Cloudflare R2 for photos.

---

## What is covered

### SQL injection
- Every query is parameterised (`%s` plus a tuple). No SQL is assembled by string
  formatting anywhere.
- User input only reaches a query through Pydantic-validated fields.

### Secrets
- `.env` is gitignored and nothing is hard-coded; every secret is read from the
  environment.
- Render and GitHub Actions hold their own secrets, none of which live in the repo.

### Database
- Row Level Security is enabled on `cars` and `searches` with no policies, which
  closes Supabase's automatic REST API to anonymous callers by default-deny.
- The backend connects directly as the owner role, which bypasses RLS, so it is
  unaffected.

### Rate limiting
- A cooldown between searches plus an hourly limit, keyed on an anonymous browser
  token with the IP as a backstop (`src/api/rate_limit.py`).
- The client IP is read from `cf-connecting-ip`, which Cloudflare overwrites and a
  client therefore cannot forge; without Cloudflare it falls back to
  `x-forwarded-for`.

### CORS
- Only the real frontend origin and the local dev ports are allowed, with
  `allow_credentials=False` and only `GET`/`POST`.

### Input validation
- Pydantic bounds everything: `query` is capped at 200 characters, `page` at
  1..200, `year` at 1900..2030, and so on. Absurd or oversized input is rejected
  before it reaches the endpoint.

### Error handling
- API errors return a machine code (`{"code": ...}`) rather than internal detail;
  the frontend turns that into a message in the user's language.
- In production the global exception handler never exposes a stack trace on a 500
  (`IS_PRODUCTION`).

### SSRF
- Photos are only fetched from the known source CDNs (autopapa, myauto) and
  written to R2. A user cannot get the backend to fetch an arbitrary URL.

---

## Known risks and things still to do

### 1. Rotate the credentials that were exposed early on
During early development some secrets were pasted into chat and logs:

- the Supabase database password
- an R2 API token (access key and secret)

**You have to do this yourself:**

1. Supabase -> Project Settings -> Database -> **Reset database password**
2. Cloudflare -> R2 -> Manage R2 API Tokens -> **delete the old token, create a new one**
3. Put the new values into Render, into GitHub Actions secrets, and into your local `.env`

A secret that has leaked once is compromised forever; rotation is the only fix.

### 2. What is actually in the git history
The history was rewritten and audited. It contains **no credentials** — every
secret-shaped value in it is a placeholder such as `NEW_PASSWORD`, and `.env` was
never committed. Two non-secret identifiers do appear in an old `DEPLOY.md`: the
Cloudflare account ID and the Supabase database hostname. Neither is usable on its
own, but since the repository is public that database endpoint is now known, which
is another reason to do the rotation in step 1.

### 3. Logging and alerting
There is no structured logging yet. Render's logs are available, but nothing
alerts on anything.

### 4. Backups
The Supabase free tier has no automatic backups. For anything production-like,
either export periodically or move to a paid plan.

---

## Worth checking now and then
- Look through the `searches` table for suspicious IPs or request patterns.
- Refresh `uv lock` to pick up dependency security patches.
