"""Photo storage — download from source CDN to local + Cloudflare R2.

R2 is S3-compatible, so boto3 works. We just point it at R2's endpoint.

Key layout (same in local and R2):
    {source}/{source_id}/{index}.jpg
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


_EXT_RE = re.compile(r"\.(jpg|jpeg|png|webp|gif)(?:\?|$)", re.IGNORECASE)

_REFERERS = {
    "autopapa": "https://autopapa.ge/",
    "myauto":   "https://www.myauto.ge/",
}


def referer_for(source: str) -> str:
    return _REFERERS.get(source, "")


def _guess_extension(url: str) -> str:
    match = _EXT_RE.search(url)
    return f".{match.group(1).lower()}" if match else ".jpg"


def make_image_key(source: str, source_id: str, index: int, url: str) -> str:
    return f"{source}/{source_id}/{index}{_guess_extension(url)}"


def local_path(key: str) -> Path:
    return PHOTOS_DIR / key


_RETRY_DELAYS = (1.0, 2.0, 4.0)


async def download_to_local(
    client: httpx.AsyncClient, url: str, key: str, source: str = ""
) -> bool:
    """Download URL → local file. Skips if already present.

    Retries 3x on transient errors (timeouts, 5xx). Permanent 4xx → no retry.
    """
    path = local_path(key)
    if path.exists() and path.stat().st_size > 0:
        return True

    path.parent.mkdir(parents=True, exist_ok=True)
    headers = {"Referer": referer_for(source)} if source else {}

    last_exc: Exception | None = None
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        try:
            resp = await client.get(url, timeout=30.0, headers=headers)
            if 400 <= resp.status_code < 500:
                log.warning("download %s — HTTP %d (no retry)", url, resp.status_code)
                return False
            resp.raise_for_status()
            # ატომური ჩაწერა: ჯერ `.part`, შემდეგ rename. შეწყვეტილი/მოკლული
            # ჩაწერა `path`-ზე ნახევარ ფაილს ვერ ტოვებს (st_size>0 check რომ
            # კორუმპირებულ სურათს არ ჩათვალოს „ჩამოწერილად").
            tmp = path.with_name(path.name + ".part")
            tmp.write_bytes(resp.content)
            tmp.replace(path)
            return True
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if attempt < len(_RETRY_DELAYS):
                await asyncio.sleep(delay)

    log.warning("download failed %s after %d tries — %s", url, len(_RETRY_DELAYS), last_exc)
    return False


_r2_client: "S3Client | None" = None


def _create_r2_client() -> "S3Client | None":
    if not r2_is_configured():
        return None
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=r2_endpoint(),
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def get_r2_client() -> "S3Client | None":
    global _r2_client
    if _r2_client is None:
        _r2_client = _create_r2_client()
    return _r2_client


def _content_type(key: str) -> str:
    ext = key.rsplit(".", 1)[-1].lower()
    return {
        "jpg":  "image/jpeg",
        "jpeg": "image/jpeg",
        "png":  "image/png",
        "webp": "image/webp",
        "gif":  "image/gif",
    }.get(ext, "image/jpeg")


def _r2_object_exists(client, key: str) -> bool:
    """HeadObject — sphenecan სწრაფი check (Class B operation, ~10x იაფი
    Class A upload-ზე). თუ ობიექტი უკვე ფაილშია, არ ვუტვირთავთ თავიდან.
    """
    from botocore.exceptions import ClientError
    try:
        client.head_object(Bucket=R2_BUCKET, Key=key)
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def upload_to_r2_sync(local_file: Path, key: str) -> bool:
    client = get_r2_client()
    if client is None:
        return False
    try:
        if _r2_object_exists(client, key):
            return True
        client.upload_file(
            str(local_file),
            R2_BUCKET,
            key,
            ExtraArgs={
                "ContentType": _content_type(key),
                "CacheControl": "public, max-age=31536000, immutable",
            },
        )
        return True
    except Exception as exc:
        log.warning("R2 upload failed %s — %s", key, exc)
        return False


async def upload_to_r2(local_file: Path, key: str) -> bool:
    return await asyncio.to_thread(upload_to_r2_sync, local_file, key)


def public_url_for(key: str) -> str:
    if not R2_PUBLIC_URL:
        return ""
    return f"{R2_PUBLIC_URL.rstrip('/')}/{key}"


async def fetch_and_store(
    client: httpx.AsyncClient,
    url: str,
    source: str,
    source_id: str,
    index: int,
    upload_to_cloud: bool = True,
    keep_local: bool = True,
) -> str | None:
    """Returns the storage key on success, None on failure.

    upload_to_cloud-ის ჩართვისას R2 upload-ის ჩავარდება None-ს აბრუნებს — key
    არ უნდა ჩაიწეროს, თუ R2-ში ფოტო ნამდვილად არ შევიდა (თორემ საიტზე გატეხილი
    სურათი გამოჩნდება და მანქანა pending-ად ვეღარ აღიქმება).

    keep_local=False — ლოკალურ ფაილს R2-ში წარმატებული upload-ის შემდეგ წაშლის
    (disk-constrained backfill: GitHub runner — ფოტოები დისკზე არ გვირჩება).
    """
    key = make_image_key(source, source_id, index, url)

    if not await download_to_local(client, url, key, source=source):
        return None

    if upload_to_cloud and r2_is_configured():
        if not await upload_to_r2(local_path(key), key):
            return None
        if not keep_local:
            try:
                local_path(key).unlink(missing_ok=True)
            except OSError:
                pass

    return key
