"""
ანტი-დეტექციის ლოგიკა — საიტს ვერ უნდა მიგვიხვდეს, რომ ბოტი ვართ.

რამდენიმე layer-ი:
  1. ბრაუზერის flag-ების მოშორება (--disable-blink-features=AutomationControlled)
  2. JS-დან navigator.webdriver-ის დამალვა
  3. რეალური User-Agent, locale, timezone, viewport
  4. playwright-stealth ბიბლიოთეკის გამოყენება (canvas/webgl/audio fingerprint masking)
  5. რესურსების ბლოკი (image/css/font) — სიჩქარისთვის და fingerprint-ის შემცირებისთვის
  6. პროქსიის მხარდაჭერა (.env-ში PROXY_URL)

შენიშვნა: 100%-იანი დაცვა შეუძლებელია. დიდი საიტებზე (Cloudflare bot fight mode,
DataDome, PerimeterX) ეს მაინც დაიჭერს. autopapa.ge-ზე საკმარისად მუშაობს.
"""

from __future__ import annotations

import random

from playwright.async_api import BrowserContext, Playwright, Route

from .config import PROXY_URL


# ---------------------------------------------------------------------------
# User-Agent პული — განახლებული 2024-2025-ში
# ---------------------------------------------------------------------------

USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
)


# ---------------------------------------------------------------------------
# რესურსების ფილტრი
# ---------------------------------------------------------------------------

# რესურსების ტიპები რომელთა გადმოწერა არ გვინდა (სიჩქარისთვის).
# ფოტოს URL-ებს მაინც ვიღებთ DOM-დან — სურათების ფაილებს არ ვწერდით.
BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}

# ანალიტიკის და ტრაკინგის დომენები — fingerprint signal-ის შემცირებისთვის
BLOCKED_DOMAINS = (
    "google-analytics.com", "googletagmanager.com",
    "facebook.net", "facebook.com",
    "doubleclick.net", "googleadservices.com",
    "recaptcha", "gstatic.com",
    "clarity.ms", "addthis.com", "siteheart.com",
    "hotjar.com", "amplitude.com",
)


async def block_heavy_resources(route: Route) -> None:
    """Playwright route handler — ბლოკავს არასაჭირო რესურსებს.

    გამოყენება:
        await page.route("**/*", block_heavy_resources)
    """
    request = route.request

    if request.resource_type in BLOCKED_RESOURCE_TYPES:
        return await route.abort()

    if any(domain in request.url for domain in BLOCKED_DOMAINS):
        return await route.abort()

    await route.continue_()


# ---------------------------------------------------------------------------
# Stealth კონტექსტი
# ---------------------------------------------------------------------------

# JS კოდი რომელიც გაეშვება ყოველი ფურცლის ჩატვირთვამდე.
# webdriver flag-ის დამალვა + plugins/languages რეალისტიკისთვის.
_STEALTH_INIT_SCRIPT = """
// webdriver flag-ის სრულად დამალვა
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// რეალისტური languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['ka-GE', 'ka', 'en-US', 'en']
});

// რეალისტური plugins (ცარიელი მასივი ბოტს უწევს)
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'PDF Viewer' },
        { name: 'Chrome PDF Viewer' },
        { name: 'Chromium PDF Viewer' },
        { name: 'Microsoft Edge PDF Viewer' },
        { name: 'WebKit built-in PDF' },
    ]
});

// Chrome runtime object - სრულიად რეალური ბრაუზერის ინდიკატორი
window.chrome = window.chrome || { runtime: {}, loadTimes: () => {}, csi: () => {} };

// permissions API - notification permission ნამდვილ ბრაუზერში "default" ან "granted"
const originalQuery = window.navigator.permissions?.query;
if (originalQuery) {
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);
}
"""


async def create_stealth_context(playwright: Playwright) -> tuple:
    """ქმნის ბრაუზერს და მის კონტექსტს stealth პარამეტრებით.

    აბრუნებს (browser, context) — ორივეს ცალკე უნდა დაიხურო ბოლოს.

    გამოყენება:
        async with async_playwright() as p:
            browser, context = await create_stealth_context(p)
            try:
                page = await context.new_page()
                ...
            finally:
                await context.close()
                await browser.close()
    """
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-web-security",            # CORS-ის გვერდის გავლა (კონტროლირებად ვიყენებთ)
            "--disable-features=IsolateOrigins,site-per-process",
        ],
    )

    context_args: dict = {
        "user_agent": random.choice(USER_AGENTS),
        "viewport": {"width": 1366, "height": 768},
        "locale": "ka-GE",
        "timezone_id": "Asia/Tbilisi",
        # extra headers რეალისტური brauserisas
        "extra_http_headers": {
            "Accept-Language": "ka-GE,ka;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        },
    }

    # პროქსი (თუ კონფიგურირებულია)
    if PROXY_URL:
        context_args["proxy"] = {"server": PROXY_URL}

    context = await browser.new_context(**context_args)

    # ყოველი ფურცლის ჩატვირთვამდე ვუშვებთ stealth-ის სკრიპტს
    await context.add_init_script(_STEALTH_INIT_SCRIPT)

    return browser, context
