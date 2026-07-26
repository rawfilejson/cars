# Playwright setup with light anti-bot measures.
#
# These won't get us past Cloudflare bot-fight or DataDome. For autopapa.ge
# and myauto.ge's current setup, this is enough.

from __future__ import annotations

import random

from playwright.async_api import Playwright, Route

from .config import PROXY_URL


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

BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}

BLOCKED_DOMAINS = (
    "google-analytics.com", "googletagmanager.com",
    "facebook.net", "facebook.com",
    "doubleclick.net", "googleadservices.com",
    "recaptcha", "gstatic.com",
    "clarity.ms", "addthis.com", "siteheart.com",
    "hotjar.com", "amplitude.com",
)


async def block_heavy_resources(route: Route) -> None:
    request = route.request

    if request.resource_type in BLOCKED_RESOURCE_TYPES:
        return await route.abort()

    if any(domain in request.url for domain in BLOCKED_DOMAINS):
        return await route.abort()

    await route.continue_()


_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

Object.defineProperty(navigator, 'languages', {
    get: () => ['ka-GE', 'ka', 'en-US', 'en']
});

Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'PDF Viewer' },
        { name: 'Chrome PDF Viewer' },
        { name: 'Chromium PDF Viewer' },
        { name: 'Microsoft Edge PDF Viewer' },
        { name: 'WebKit built-in PDF' },
    ]
});

window.chrome = window.chrome || { runtime: {}, loadTimes: () => {}, csi: () => {} };

const originalQuery = window.navigator.permissions?.query;
if (originalQuery) {
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);
}
"""


async def create_stealth_context(playwright: Playwright) -> tuple:
    # Returns (browser, context). Caller must close both.
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-features=IsolateOrigins,site-per-process",
        ],
    )

    context_args = {
        "user_agent": random.choice(USER_AGENTS),
        "viewport": {"width": 1366, "height": 768},
        "locale": "ka-GE",
        "timezone_id": "Asia/Tbilisi",
        "extra_http_headers": {
            "Accept-Language": "ka-GE,ka;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        },
    }

    if PROXY_URL:
        context_args["proxy"] = {"server": PROXY_URL}

    context = await browser.new_context(**context_args)
    await context.add_init_script(_STEALTH_INIT_SCRIPT)

    return browser, context
