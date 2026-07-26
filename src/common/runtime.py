# asyncio + Windows console glue.
# Two Windows-specific annoyances we hide here:
#   - stdout defaults to cp1252 and crashes on Georgian text
#   - some libraries like older psycopg async prefer SelectorEventLoop
# We leave the default event loop (ProactorEventLoop) alone because
# Playwright needs it for subprocesses. psycopg runs sync in a thread instead
# (see db.py).

from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine
from typing import TypeVar


T = TypeVar("T")


def _configure_windows_runtime() -> None:
    if sys.platform != "win32":
        return

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def run(coro: Coroutine[None, None, T]) -> T:
    _configure_windows_runtime()
    return asyncio.run(coro)
