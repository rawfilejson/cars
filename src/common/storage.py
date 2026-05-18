"""
ფოტოების შენახვა — ლოკალურად + Cloudflare R2-ში.

R2 არის S3-compatible storage — ვიყენებთ boto3-ით, მხოლოდ endpoint-ი
სხვაა. ფასი: ~$0.015/GB/თვე, zero egress fees (ე.ი. წაკითხვა უფასოა).

სტრუქტურა:
  ლოკალური: photos/{source}/{car_id}/{index}.jpg
  R2:       {source}/{car_id}/{index}.jpg

key-ი ერთიდაიგივეა ორივეგან — ერთხელ რომ ვიცოდე, ორივეგან ვიპოვი.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from .config import (
    PHOTOS_DIR,
    R2_ACCESS_KEY_ID,
    R2_BUCKET,
    R2_PUBLIC_URL,
    R2_SECRET_ACCESS_KEY,
    r2_endpoint,
    r2_is_configured,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ფაილის გაფართოების ამოცნობა URL-დან
# ---------------------------------------------------------------------------

_EXT_RE = re.compile(r"\.(jpg|jpeg|png|webp|gif)(?:\?|$)", re.IGNORECASE)


def _guess_extension(url: str) -> str:
    """URL-დან ფაილის გაფართოების ამოღება. default: .jpg."""
    match = _EXT_RE.search(url)
    return f".{match.group(1).lower()}" if match else ".jpg"


def make_image_key(source: str, source_id: str, index: int, url: str) -> str:
    """R2-სა და ლოკალურ საქაღალდეში გამოყენებული გასაღები (key)."""
    ext = _guess_extension(url)
    return f"{source}/{source_id}/{index}{ext}"


# ---------------------------------------------------------------------------
# ლოკალური საქაღალდე
# ---------------------------------------------------------------------------


def local_path(key: str) -> Path:
    """key-ის შესაბამისი ლოკალური ფაილის გზა."""
    return PHOTOS_DIR / key


async def download_to_local(
    client: httpx.AsyncClient, url: str, key: str
) -> bool:
    """ფოტოს გადმოწერა და ლოკალურ ფაილში შენახვა.

    აბრუნებს True თუ წარმატებით ჩაიწერა, False — თუ ცდუნდა.
    """
    path = local_path(key)
    if path.exists() and path.stat().st_size > 0:
        return True                                  # უკვე გადმოწერილია

    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        resp = await client.get(url, timeout=30.0)
        resp.raise_for_status()
        path.write_bytes(resp.content)
        return True
    except Exception as exc:
        log.warning("download failed %s — %s", url, exc)
        return False


# ---------------------------------------------------------------------------
# R2 — S3-compatible upload
# ---------------------------------------------------------------------------


def _create_r2_client() -> "S3Client | None":
    """R2 client-ის შექმნა. None თუ კონფიგი ცარიელია."""
    if not r2_is_configured():
        return None

    import boto3                                     # lazy import — სიჩქარისთვის

    return boto3.client(
        "s3",
        endpoint_url=r2_endpoint(),
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",                          # R2-ისთვის "auto" სტანდარტია
    )


_r2_client: "S3Client | None" = None


def get_r2_client() -> "S3Client | None":
    """Cached R2 client — ერთხელ ვქმნით, ხელახლა ვიყენებთ."""
    global _r2_client
    if _r2_client is None:
        _r2_client = _create_r2_client()
    return _r2_client


def upload_to_r2_sync(local_file: Path, key: str) -> bool:
    """ლოკალური ფაილის ატვირთვა R2-ში. boto3 sync-ია — async-ში to_thread-ით ვუშვებთ."""
    client = get_r2_client()
    if client is None:
        return False

    try:
        client.upload_file(
            str(local_file),
            R2_BUCKET,
            key,
            ExtraArgs={"ContentType": _content_type(key)},
        )
        return True
    except Exception as exc:
        log.warning("R2 upload failed %s — %s", key, exc)
        return False


async def upload_to_r2(local_file: Path, key: str) -> bool:
    """async wrapper sync upload-ისთვის."""
    return await asyncio.to_thread(upload_to_r2_sync, local_file, key)


def _content_type(key: str) -> str:
    """MIME ტიპის გამოცნობა გაფართოებიდან."""
    ext = key.rsplit(".", 1)[-1].lower()
    return {
        "jpg":  "image/jpeg",
        "jpeg": "image/jpeg",
        "png":  "image/png",
        "webp": "image/webp",
        "gif":  "image/gif",
    }.get(ext, "image/jpeg")


def public_url_for(key: str) -> str:
    """R2 public URL მოცემული key-სთვის."""
    if not R2_PUBLIC_URL:
        return ""
    return f"{R2_PUBLIC_URL.rstrip('/')}/{key}"


# ---------------------------------------------------------------------------
# ერთად — გადმოწერა + R2 ატვირთვა
# ---------------------------------------------------------------------------


async def fetch_and_store(
    client: httpx.AsyncClient,
    url: str,
    source: str,
    source_id: str,
    index: int,
    upload_to_cloud: bool = True,
) -> str | None:
    """ერთი ფოტოს გადმოწერა → ლოკალური ფაილი → (არასავალდებულო) R2 ატვირთვა.

    აბრუნებს key-ს თუ წარმატებით შენახა, None — თუ ცდუნდა.
    """
    key = make_image_key(source, source_id, index, url)

    ok = await download_to_local(client, url, key)
    if not ok:
        return None

    if upload_to_cloud and r2_is_configured():
        await upload_to_r2(local_path(key), key)

    return key
