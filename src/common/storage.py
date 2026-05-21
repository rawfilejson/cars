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


def _guess_extension(url: str) -> str:
    match = _EXT_RE.search(url)
    return f".{match.group(1).lower()}" if match else ".jpg"


def make_image_key(source: str, source_id: str, index: int, url: str) -> str:
    return f"{source}/{source_id}/{index}{_guess_extension(url)}"


def local_path(key: str) -> Path:
    return PHOTOS_DIR / key


async def download_to_local(client: httpx.AsyncClient, url: str, key: str) -> bool:
    path = local_path(key)
    if path.exists() and path.stat().st_size > 0:
        return True

    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        resp = await client.get(url, timeout=30.0)
        resp.raise_for_status()
        path.write_bytes(resp.content)
        return True
    except Exception as exc:
        log.warning("download failed %s — %s", url, exc)
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


def upload_to_r2_sync(local_file: Path, key: str) -> bool:
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
) -> str | None:
    """Returns the storage key on success, None on failure."""
    key = make_image_key(source, source_id, index, url)

    if not await download_to_local(client, url, key):
        return None

    if upload_to_cloud and r2_is_configured():
        await upload_to_r2(local_path(key), key)

    return key
