# Respect the source's robots.txt: check before fetching anything.
#
# It is read once per host and cached. If it cannot be read we allow the fetch,
# since a missing robots.txt is not a prohibition.

from __future__ import annotations

import asyncio
import logging
import urllib.robotparser
from urllib.parse import urlsplit


log = logging.getLogger(__name__)

_cache: dict[str, urllib.robotparser.RobotFileParser] = {}


def _load_sync(origin: str) -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(f"{origin}/robots.txt")
    try:
        rp.read()
    except Exception as exc:
        log.warning("robots.txt read failed for %s (%s) - defaulting to allow", origin, exc)
        rp.parse([])
    return rp


async def can_fetch(url: str, user_agent: str = "*") -> bool:
    # True when robots.txt does not forbid this URL for this user-agent
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return True
    origin = f"{parts.scheme}://{parts.netloc}"
    rp = _cache.get(origin)
    if rp is None:
        rp = await asyncio.to_thread(_load_sync, origin)
        _cache[origin] = rp
    try:
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True
