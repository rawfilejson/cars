"""Project configuration — everything tunable lives here.

Values come from environment variables (or .env file via python-dotenv).
Secrets never live in code.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://cars:cars@localhost:5432/cars",
)


R2_ACCOUNT_ID: str = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID: str = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY: str = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET: str = os.getenv("R2_BUCKET", "cars-photos")
R2_PUBLIC_URL: str = os.getenv("R2_PUBLIC_URL", "")


def r2_endpoint() -> str:
    if not R2_ACCOUNT_ID:
        return ""
    return f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"


def r2_is_configured() -> bool:
    return bool(R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY)


PHOTOS_DIR: Path = Path(os.getenv("PHOTOS_DIR", ROOT_DIR / "photos")).resolve()


PROXY_URL: str = os.getenv("PROXY_URL", "")


CONCURRENT_PAGES: int = int(os.getenv("CONCURRENT_PAGES", "10"))
RETRY_PER_CAR: int = int(os.getenv("RETRY_PER_CAR", "2"))
PAGE_TIMEOUT_MS: int = int(os.getenv("PAGE_TIMEOUT_MS", "25000"))


# SEARCH_LIMIT_PER_HOUR <= 0 → საათობრივი ლიმიტი გამორთულია (მხოლოდ cooldown მოქმედებს)
SEARCH_LIMIT_PER_HOUR: int = int(os.getenv("SEARCH_LIMIT_PER_HOUR", "0"))
SEARCH_COOLDOWN_SECONDS: int = int(os.getenv("SEARCH_COOLDOWN_SECONDS", "10"))
SEARCH_LIMIT_PER_IP_HOUR: int = int(os.getenv("SEARCH_LIMIT_PER_IP_HOUR", "3000"))


CONTACT_INSTAGRAM: str = os.getenv("CONTACT_INSTAGRAM", "@deme.brn")
