# უსაფრთხოება

> "აბსოლუტურად დაცული" არ არსებობს. მიზანი — გონივრულად დაცული, მინიმალური attack surface.

საიტი **ანონიმური და უფასოა**: არ არის ავტორიზაცია, არ არის გადახდა, არ ვაგროვებთ
პერსონალურ მონაცემებს. ეს თავისთავად ამცირებს რისკებს.

არქიტექტურა: Cloudflare Workers (static frontend) → Render (FastAPI backend)
→ Supabase PostgreSQL + Cloudflare R2 (ფოტოები).

---

## რა არის დაცული

### SQL Injection
- ყველა query parametrized (`%s` + tuple). string-formatting-ით აწყობილი SQL არსად არის.
- მომხმარებლის ინფუთი მხოლოდ Pydantic-ვალიდირებული ველებით შემოდის.

### Secrets
- `.env` .gitignore-შია; კოდში secret hard-coded არ არის — ყველაფერი env-ცვლადებიდან იკითხება.
- Render-ისა და GitHub Actions-ის secrets ცალკეა და repo-ში არ ინახება.

### მონაცემთა ბაზა
- RLS (Row Level Security) ჩართულია `cars` და `searches` ცხრილებზე policy-ების გარეშე —
  Supabase-ის auto-REST API-ის ანონიმური წვდომა default-deny-ით იხურება.
- backend პირდაპირ უკავშირდება DB-ს owner role-ით (RLS bypass), ამიტომ მისი მუშაობა არ ფერხდება.

### Rate limiting (anti-abuse)
- IP-ზე cooldown ცდებს შორის + საათობრივი ლიმიტი (`src/api/rate_limit.py`).
- IP იკითხება `cf-connecting-ip` header-იდან (Cloudflare proxy წინაშეა), შემდეგ `x-forwarded-for`.

### CORS
- დაშვებულია მხოლოდ ნამდვილი frontend origin + ლოკალური dev პორტები.
  `allow_credentials=False`, მეთოდები მხოლოდ `GET`/`POST`.

### Input validation
- Pydantic: query `max_length=200`, page `1..200`, year `1900..2030` და ა.შ. —
  ზედმეტად გრძელი ან აბსურდული ინფუთი იჭრება ჯერ კიდევ endpoint-მდე.

### Error handling
- API შეცდომები აბრუნებს მანქანურ კოდს (`{"code": ...}`), არა შიდა დეტალებს —
  frontend თარგმნის მომხმარებლის ენაზე.
- production-ში global exception handler 500-ზე stack trace-ს არ ამხელს (`IS_PRODUCTION`).

### SSRF
- ფოტოებს ვტვირთავთ მხოლოდ ცნობილი წყაროების CDN-იდან (autopapa / myauto) და ვწერთ R2-ში.
  თვითნებურ URL-ს მომხმარებელი backend-ს ვერ აწვდის.

---

## დარჩენილი რისკები და გასაკეთებელი

### 1. 🔴 ადრეული secrets გასაჟონა — როტაცია სავალდებულოა
განვითარების ადრეულ ეტაპზე რამდენიმე secret გადაიცა chat/log-ში და მოხვდა git-ის ისტორიაში:
- Supabase DB password
- R2 API token (access key + secret)

**აუცილებელი მოქმედება (მხოლოდ შენ შეგიძლია):**
1. Supabase → Project Settings → Database → **Reset database password**.
2. Cloudflare → R2 → Manage R2 API Tokens → **ძველი token წაშალე, ახალი შექმენი**.
3. ახალი მნიშვნელობები ჩასვი Render-ისა და GitHub Actions-ის secrets-ში (+ ლოკალურ `.env`-ში).

ერთხელ გასაჟონილი secret სამუდამოდ "compromised"-ად ითვლება — როტაცია ერთადერთი გამოსავალია.

### 2. Secrets git-ის ისტორიაში
ზემოთ ნახსენები secrets (და ძველი `auth.json`) ჯერ კიდევ git-ის ისტორიაშია. ისტორიის გადაწერა
(`git filter-repo`) + force-push ცალკე ნაბიჯია; ის secret-ებს "უსაფრთხოს" არ ხდის — **როტაცია
მაინც სავალდებულოა** (იხ. #1).

### 3. Logging / alerting
სტრუქტურირებული ლოგინგი ჯერ არ გვაქვს. Render-ის ლოგები ხელმისაწვდომია, მაგრამ ცალკე alerting არ არის.

### 4. Backups
Supabase free tier ავტომატურ backup-ს არ აძლევს. production-ისთვის რეკომენდებულია პერიოდული
ხელით export ან Pro-ზე ატანა.

---

## პერიოდული შემოწმება
- `searches` ცხრილის გადახედვა — საეჭვო IP / ცდის pattern-ები.
- `uv lock`-ის განახლება — დამოკიდებულებების security patch-ები.
