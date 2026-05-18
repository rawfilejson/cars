# უსაფრთხოების Audit

> ⚠️ "აბსოლუტურად დაცული" შეუძლებელია. ჩვენი მიზანი — **გონივრულად დაცული + სწრაფი ინციდენტ-რეაგირება**.

ეს დოკუმენტი აღწერს რა გავაკეთეთ უსაფრთხოებისთვის, რა რისკები რჩება, და რა უნდა გავაკეთოთ deploy-მდე / შემდეგ.

---

## 🟢 რა გვაქვს უკვე გაკეთებული

### SQL Injection
- ✅ ყველგან parametrized queries (`%(name)s` ან `%s` + tuple)
- ✅ არანაირი string formatting SQL-ში
- ✅ psycopg ავტომატურად escape-ს უკეთებს

### Secrets Management
- ✅ `.env` ფაილი .gitignore-ში
- ✅ კოდში არცერთი secret არ არის hard-coded
- ✅ GitHub Actions secrets-ი ცალკე
- ✅ Supabase Service Role Key — მხოლოდ backend-ში (frontend-ში არ მიდის)

### Authentication
- ✅ Supabase Auth — JWT-ით (industry standard)
- ✅ JWT verification ხდება backend-ში HS256-ით
- ✅ Token expiry ავტომატურად მოწმდება

### Database
- ✅ Row Level Security ჩართულია ყველა ცხრილზე
- ✅ Supabase auto-REST API anonymous user-ისთვის ცარიელია (default deny)
- ✅ Backend პირდაპირ DB-სთან კავშირდება (postgres role) — RLS bypass

### Rate Limiting
- ✅ 15წმ cooldown ცდებს შორის
- ✅ Free tier: 2 lifetime ცდა per IP/user
- ✅ Paid tier: 35/5h
- ✅ IP-ის ნამდვილი მნიშვნელობა `cf-connecting-ip` header-დან (Cloudflare-ი წინაშე)

### Privacy
- ✅ ვინახავთ მხოლოდ: user_id (UUID), email, subscription status
- ✅ არ ვინახავთ: password, payment details (Stripe/BOG-ი თვითონ ინახავს)
- ✅ Search log-ში: query, user_id ან IP, timestamp — გრძელვადიანი audit-ისთვის

---

## 🟡 რისკები რომელიც ჯერ რჩება

### 1. დღევანდელი secrets გადაცემული საუბრის ისტორიაში
**პრობლემა:** dialogue-ის ისტორიაში დატანილია:
- Supabase DB password (`D)tqurs,*%.tq`)
- R2 Access Key + Secret + Token
- Supabase JWT Secret
- Supabase service_role key

**რა გავაკეთოთ ეხლავე deploy-მდე:**
1. **Supabase**: Dashboard → Project Settings → Database → "Reset database password" — შეცვალე
2. **Supabase**: Dashboard → Project Settings → API → "Reset JWT secret" — შეცვალე
3. **Cloudflare R2**: Dashboard → R2 → Manage R2 API Tokens → წაშალე ძველი token, შექმენი ახალი
4. შემდეგ ჩაანაცვლე `.env`-ში ახალი მნიშვნელობები

ჩვენი დიალოგი არ არის long-term-ად უსაფრთხო არხი secrets-ის გასატარებლად. ერთხელ რომ secret-ი გადასცილდი ლოგებში, ის "compromised"-ად ითვლება.

### 2. SQL Error Messages-ი user-ს ენახება
**პრობლემა:** FastAPI default-ად ფლეშავს exception-ის სრულ details-ს.

**ფიქსი:** production-ში დავამატოთ exception handler რომ შიდა details არ წავიდეს client-ს.

### 3. CSRF არ გვაქვს
**პრობლემა:** POST endpoints-ი ერთობ უაცილოა CSRF attack-ისთვის.

**მიტიგაცია ჯერ:** Backend-ი ცალკე origin-ზე (Fly.io), frontend-ი Cloudflare Pages-ზე. CORS strict mode დააფიქსებს origin-ს, ე.ი. attacker site-მა fetch ვერ გააკეთებს.

**მერე:** SameSite=Strict cookies + CSRF tokens state-changing endpoints-ისთვის.

### 4. No request size limits
**პრობლემა:** მომხმარებელს შეუძლია გრძელი search query გამოაგზავნოს — DoS.

**მიტიგაცია:** Pydantic-ში `max_length` ვაყენებთ. + Cloudflare WAF რეგ.ლიმიტებს ფარავს.

### 5. Logging არ გვაქვს
**პრობლემა:** თუ რამე ჩავარდა production-ში, ვერ ვიცით რა მოხდა.

**ფიქსი:** Fly.io-ში logs ნახვა შესაძლებელია (`flyctl logs`). Production-ში დავამატოთ structured logging (loguru ან Python's logging-ით).

### 6. Backups
**Supabase Pro:** ყოველდღე ავტომატური backup, 7 დღე retention
**Free:** არ აქვს — Pro-ზე upgrade აუცილებელია production-ისთვის

### 7. DDoS / Bot Protection
**Cloudflare Free:** ბაზისური bot protection ჩართულია (challenge რთულ requests-ს)
**Cloudflare Pro ($20/მ)** : მეტი fine-grained WAF rules — production-ში მიგვაჩნია სასარგებლოდ

### 8. Subscription/Payment integrity
**ჯერ არ გვაქვს implemented.** როცა BOG/TBC ვამატებთ:
- Webhook signature verification აუცილებელია (rotateable secret)
- Server-side ვერიფიკაცია — client-ს არ ვენდობით
- Idempotency keys მრავალი ჩარიცხვის avoidance-ისთვის

---

## 🔴 რა აუცილებლად უნდა გავაკეთო Deploy-მდე

### Pre-deploy checklist:
- [ ] **Secrets rotate** (იხ. რისკი #1)
- [ ] Production CORS — მხოლოდ ნამდვილი frontend domain
- [ ] Exception handler რომ stack traces არ წავიდეს client-ს
- [ ] Cloudflare Free tier ჩართე frontend domain-ისთვის (DDoS bot protection)
- [ ] DB connection pooling (psycopg-ი connect/disconnect every call ახლა — slow)

### Post-deploy რეგულარული:
- ყოველთვიური password rotation production-ში
- ყოველთვიური review searches-ის: საეჭვო IP-ები, ცდის pattern-ები
- Quarterly security review

---

## OWASP Top 10 Coverage

| OWASP | სტატუსი | მითითება |
|-------|---------|----------|
| A01 Broken Access Control | 🟢 OK | RLS + JWT verification |
| A02 Cryptographic Failures | 🟢 OK | HTTPS-ი deploy-ის შემდეგ აუცილებელია |
| A03 Injection | 🟢 OK | Parametrized queries |
| A04 Insecure Design | 🟡 Partial | Rate limit გვაქვს, scaling-ი ჯერ ცარიელი |
| A05 Security Misconfiguration | 🟡 Partial | CORS strict, exception handler ჯერ არა |
| A06 Vulnerable Components | 🟡 Partial | Dependabot / `uv lock` განახლება |
| A07 Auth Failures | 🟢 OK | Supabase Auth |
| A08 Software/Data Integrity | 🟢 OK | Signed JWTs, pyproject.toml lock |
| A09 Logging Failures | 🔴 Missing | აუცილებელია გავაკეთოთ deploy-მდე |
| A10 Server-Side Request Forgery | 🟢 OK | photo URL-ები external-ად, ვწერთ მხოლოდ R2 + autopapa-დან |
