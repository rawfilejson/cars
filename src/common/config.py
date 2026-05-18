"""
პროექტის კონფიგურაცია.

ყველა მნიშვნელოვანი პარამეტრი (database connection, R2 credentials, ...) აქედან
იკითხება, ხოლო ნამდვილი მნიშვნელობები .env ფაილში გვაქვს. ეს ნიშნავს რომ
პაროლები არასოდეს არ აქვს კოდში — git-ში არასოდეს არ ვააფიქსირებთ .env-ს.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


# პროექტის ფესვი — სადაც pyproject.toml ცხოვრობს
ROOT_DIR = Path(__file__).resolve().parents[2]

# .env ფაილის ჩატვირთვა (თუ არსებობს)
load_dotenv(ROOT_DIR / ".env")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://cars:cars@localhost:5432/cars",
)


# ---------------------------------------------------------------------------
# Cloudflare R2 (S3-compatible object storage)
# ---------------------------------------------------------------------------

R2_ACCOUNT_ID: str = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID: str = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY: str = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET: str = os.getenv("R2_BUCKET", "cars-photos")
R2_PUBLIC_URL: str = os.getenv("R2_PUBLIC_URL", "")


def r2_endpoint() -> str:
    """R2-ის API endpoint — account_id-დან წარმოიქმნება."""
    if not R2_ACCOUNT_ID:
        return ""
    return f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"


def r2_is_configured() -> bool:
    """შემოწმება — გვაქვს თუ არა R2 credentials. ცარიელის შემთხვევაში მხოლოდ
    ლოკალურ საქაღალდეში ვინახავთ ფოტოებს."""
    return bool(R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY)


# ---------------------------------------------------------------------------
# ფოტოების ლოკალური საქაღალდე
# ---------------------------------------------------------------------------

PHOTOS_DIR: Path = Path(os.getenv("PHOTOS_DIR", ROOT_DIR / "photos")).resolve()


# ---------------------------------------------------------------------------
# პროქსი (არასავალდებულო)
# ---------------------------------------------------------------------------

PROXY_URL: str = os.getenv("PROXY_URL", "")


# ---------------------------------------------------------------------------
# პარსერის ქცევა
# ---------------------------------------------------------------------------

CONCURRENT_PAGES: int = int(os.getenv("CONCURRENT_PAGES", "10"))
RETRY_PER_CAR: int = int(os.getenv("RETRY_PER_CAR", "2"))
PAGE_TIMEOUT_MS: int = int(os.getenv("PAGE_TIMEOUT_MS", "25000"))


# ---------------------------------------------------------------------------
# Web API — სრულიად უფასო, ლიმიტი მხოლოდ IP-ით
# ---------------------------------------------------------------------------

# IP-ის მიხედვით რამდენი ძიება შეიძლება საათში
SEARCH_LIMIT_PER_HOUR: int = int(os.getenv("SEARCH_LIMIT_PER_HOUR", "30"))

# Cooldown — ცდებს შორის მინიმუმ ამდენი წამი
SEARCH_COOLDOWN_SECONDS: int = int(os.getenv("SEARCH_COOLDOWN_SECONDS", "10"))

# კონტაქტი ლიმიტის გადასაცილებლად
CONTACT_INSTAGRAM: str = os.getenv("CONTACT_INSTAGRAM", "@barni_brn")
