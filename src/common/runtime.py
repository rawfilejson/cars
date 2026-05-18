"""
asyncio-ს გასაშვები helper.

Windows-ზე ორი პრობლემაა default კონფიგში:
  1. ProactorEventLoop — psycopg async-ი ვერ მუშაობს მასთან. ვჭირდება SelectorEventLoop.
  2. stdout-ი cp1252 encoding-ით — ქართული სიმბოლოები crash-ს იწვევს print-ის დროს.
ორივეს აქ ვწყვეტთ.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine
from typing import TypeVar


T = TypeVar("T")


def _configure_windows_runtime() -> None:
    """Windows-სპეციფიკური ერთჯერადი setup.

    შენიშვნა: ProactorEventLoop-ს ვტოვებთ default-ად — Playwright-ს ეს ჭირდება
    subprocess-ისთვის. psycopg-ი sync რეჟიმში მუშაობს thread-ში (იხ. db.py),
    ამიტომ event loop-ის ტიპს არ აქვს მნიშვნელობა.
    """
    if sys.platform != "win32":
        return

    # UTF-8 stdout/stderr — რომ ქართულმა ტექსტმა არ ააფეთქოს print-ი
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass                                # უძველეს Python-ში reconfigure არ არსებობს


def run(coro: Coroutine[None, None, T]) -> T:
    """ჩვენი asyncio.run-ის შემცვლელი."""
    _configure_windows_runtime()
    return asyncio.run(coro)
