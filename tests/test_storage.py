"""storage.py — key gen, idempotent download, retry, R2 head-check."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from src.common import storage


@pytest.mark.parametrize("url,expected_ext", [
    ("https://x.com/a/b/c.jpg", ".jpg"),
    ("https://x.com/a/b/c.jpeg", ".jpeg"),
    ("https://x.com/a/b/c.png?v=1", ".png"),
    ("https://x.com/a/b/c.webp", ".webp"),
    ("https://x.com/no-ext", ".jpg"),
    ("https://x.com/a/b/c.JPG", ".jpg"),
])
def test_guess_extension(url, expected_ext):
    assert storage._guess_extension(url) == expected_ext


def test_make_image_key():
    key = storage.make_image_key("autopapa", "12345", 3, "https://x.com/p.jpg")
    assert key == "autopapa/12345/3.jpg"


def test_make_image_key_with_query_string():
    key = storage.make_image_key("myauto", "999", 1, "https://x.com/a.webp?v=11")
    assert key == "myauto/999/1.webp"


@pytest.mark.parametrize("source,expected", [
    ("autopapa", "https://autopapa.ge/"),
    ("myauto",   "https://www.myauto.ge/"),
    ("unknown",  ""),
    ("",         ""),
])
def test_referer_for(source, expected):
    assert storage.referer_for(source) == expected


@pytest.fixture
def temp_photos_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(storage, "PHOTOS_DIR", Path(tmp))
        yield Path(tmp)


@pytest.fixture
def fast_retries(monkeypatch):
    """No actual sleeping between retries in tests."""
    monkeypatch.setattr(storage, "_RETRY_DELAYS", (0, 0, 0))


def make_mock_client(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


async def test_download_to_local_writes_file(temp_photos_dir, fast_retries):
    def handler(request):
        return httpx.Response(200, content=b"fake-jpeg-bytes")

    async with make_mock_client(handler) as client:
        ok = await storage.download_to_local(client, "https://x/a.jpg", "src/123/1.jpg")
    assert ok
    file = temp_photos_dir / "src/123/1.jpg"
    assert file.exists()
    assert file.read_bytes() == b"fake-jpeg-bytes"


async def test_download_to_local_atomic_no_part_file_left(temp_photos_dir, fast_retries):
    """Success writes the complete final file via a temp `.part`, then renames —
    no half-written file and no leftover `.part` on success."""
    def handler(request):
        return httpx.Response(200, content=b"complete-bytes")

    async with make_mock_client(handler) as client:
        ok = await storage.download_to_local(client, "https://x/a.jpg", "src/9/1.jpg")
    assert ok
    final = temp_photos_dir / "src/9/1.jpg"
    assert final.read_bytes() == b"complete-bytes"
    assert not (temp_photos_dir / "src/9/1.jpg.part").exists()


async def test_download_to_local_skips_if_exists(temp_photos_dir, fast_retries):
    target = temp_photos_dir / "src/123/1.jpg"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"cached")

    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=b"new")

    async with make_mock_client(handler) as client:
        ok = await storage.download_to_local(client, "https://x/a.jpg", "src/123/1.jpg")

    assert ok
    assert len(calls) == 0
    assert target.read_bytes() == b"cached"


async def test_download_to_local_retries_on_5xx(temp_photos_dir, fast_retries):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503)
        return httpx.Response(200, content=b"ok")

    async with make_mock_client(handler) as client:
        ok = await storage.download_to_local(client, "https://x/a.jpg", "src/1/1.jpg")
    assert ok
    assert len(calls) == 3


async def test_download_to_local_no_retry_on_4xx(temp_photos_dir, fast_retries):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(404)

    async with make_mock_client(handler) as client:
        ok = await storage.download_to_local(client, "https://x/a.jpg", "src/1/1.jpg")
    assert not ok
    assert len(calls) == 1


async def test_download_to_local_gives_up_after_max_retries(temp_photos_dir, fast_retries):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    async with make_mock_client(handler) as client:
        ok = await storage.download_to_local(client, "https://x/a.jpg", "src/1/1.jpg")
    assert not ok
    assert len(calls) == len(storage._RETRY_DELAYS)


async def test_download_to_local_uses_referer(temp_photos_dir, fast_retries):
    captured = []
    def handler(request):
        captured.append(request.headers.get("referer", ""))
        return httpx.Response(200, content=b"x")

    async with make_mock_client(handler) as client:
        await storage.download_to_local(
            client, "https://x/a.jpg", "src/1/1.jpg", source="myauto"
        )
    assert captured[0] == "https://www.myauto.ge/"


def make_r2_client_mock(existing_keys: set[str]) -> MagicMock:
    """Mock boto3 S3 client with HeadObject that returns 404 for unknown keys."""
    from botocore.exceptions import ClientError

    client = MagicMock()
    client.upload_file = MagicMock()

    def head_object(**kwargs):
        if kwargs["Key"] in existing_keys:
            return {}
        err = {"Error": {"Code": "404", "Message": "Not Found"}}
        raise ClientError(err, "HeadObject")
    client.head_object = MagicMock(side_effect=head_object)
    return client


def test_r2_object_exists_true():
    client = make_r2_client_mock({"x/y/1.jpg"})
    assert storage._r2_object_exists(client, "x/y/1.jpg")


def test_r2_object_exists_false():
    client = make_r2_client_mock(set())
    assert not storage._r2_object_exists(client, "x/y/1.jpg")


def test_upload_to_r2_sync_skips_if_exists(monkeypatch, tmp_path):
    file = tmp_path / "a.jpg"
    file.write_bytes(b"x")

    client = make_r2_client_mock({"src/1/1.jpg"})
    monkeypatch.setattr(storage, "get_r2_client", lambda: client)

    ok = storage.upload_to_r2_sync(file, "src/1/1.jpg")
    assert ok
    client.upload_file.assert_not_called()


def test_upload_to_r2_sync_uploads_when_missing(monkeypatch, tmp_path):
    file = tmp_path / "a.jpg"
    file.write_bytes(b"x")

    client = make_r2_client_mock(set())
    monkeypatch.setattr(storage, "get_r2_client", lambda: client)

    ok = storage.upload_to_r2_sync(file, "src/1/1.jpg")
    assert ok
    client.upload_file.assert_called_once()
