# Security

> Nothing is "completely secure".

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
- `.env` is gitignored and nothing is hard-coded.
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
  client therefore cannot forge. without Cloudflare it falls back to
  `x-forwarded-for`.

### CORS
- Only the real frontend origin and the local dev ports are allowed, with
  `allow_credentials=False` and only `GET`/`POST`.

### Input validation
- Pydantic bounds everything: `query` is capped at 200 characters, `page` at
  1-200, `year` at 1900-2030, and so on. Absurd or oversized input is rejected
  before it reaches the endpoint.

### Error handling
- API errors return a machine code (`{"code": ...}`) rather than internal detail.
  the frontend turns that into a message in the user's language.
- In production the global exception handler never exposes a stack trace on a 500
  (`IS_PRODUCTION`).

### SSRF
- Photos are only fetched from the known source CDNs (autopapa, myauto) and
  written to R2. A user cannot get the backend to fetch an arbitrary URL.

---