# Remove listings that have disappeared from their source site.
#
# A listing is a *candidate* when nothing has touched it in --days. Note
# the scrapers skip listings that are already saved, so an old updated_at
# does NOT mean the listing is gone - every candidate is verified against
# the source, and only listings the source confirms are gone get deleted.
# Anything unverifiable (blocked, timeout, odd status) is skipped - we
# never delete on doubt. Verified-alive rows get their updated_at bumped
# (with --apply) so successive runs move on to new candidates.
#
# dry run prints what would happen. --apply deletes
#
#     DATABASE_URL=postgresql://... uv run python scripts/prune_dead.py
#     DATABASE_URL=postgresql://... uv run python scripts/prune_dead.py --apply --days 30 --limit 500

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
import psycopg  # noqa: E402


MYAUTO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) CLDB 2.1.3.08; Chrome/129.0.0.0; Safari/537.36"
)
DELAY_SECONDS = 0.35   # be polite to the sources


def check_myauto(client: httpx.Client, source_id: str) -> str:
    # 'alive' | 'dead' | 'unknown' for a myauto listing.
    try:
        r = client.get(
            f"https://api2.myauto.ge/ka/products/{source_id}",
            headers={
                "Accept": "*/*",
                "Accept-Language": "ka",
                "Origin": "https://myauto.ge",
                "Referer": "https://myauto.ge/",
                "User-Agent": MYAUTO_UA,
            },
            timeout=15,
        )
    except Exception:
        return "unknown"
    if r.status_code == 404:
        return "dead"
    if r.status_code != 200:
        return "unknown"
    try:
        data = r.json().get("data") or {}
    except Exception:
        return "unknown"
    # the API answers 200 with an empty/blank payload for removed listings
    prod = data.get("product") if isinstance(data, dict) else None
    if not prod:
        return "dead"
    status = prod.get("status_id")
    # myauto status: 1 = active. anything else (sold/hidden/expired) is gone
    if status is not None and status != 1:
        return "dead"
    return "alive"


def check_autopapa(client: httpx.Client, url: str) -> str:
    try:
        r = client.get(url, timeout=15, follow_redirects=True)
    except Exception:
        return "unknown"
    if r.status_code == 404 or r.status_code == 410:
        return "dead"
    if r.status_code != 200:
        return "unknown"
    # deleted autopapa listings redirect to the search page
    if "/search" in str(r.url):
        return "dead"
    return "alive"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="not re-seen for N days -> candidate")
    ap.add_argument("--limit", type=int, default=300, help="max candidates to verify this run")
    ap.add_argument("--apply", action="store_true", help="actually delete confirmed-dead rows")
    args = ap.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("set DATABASE_URL to the Postgres connection string")

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '120s'")
            cur.execute(
                """
                SELECT id, source, source_id, url
                FROM cars
                WHERE updated_at < now() - make_interval(days => %s)
                ORDER BY updated_at ASC
                LIMIT %s
                """,
                (args.days, args.limit),
            )
            candidates = cur.fetchall()

        print(f"candidates not re-seen in {args.days}+ days: {len(candidates)}")
        if not candidates:
            return

        dead: list[int] = []
        alive: list[int] = []
        unknown = 0
        with httpx.Client() as client:
            for cid, source, source_id, url in candidates:
                if source == "myauto":
                    verdict = check_myauto(client, source_id)
                elif source == "autopapa":
                    verdict = check_autopapa(client, url)
                else:
                    verdict = "unknown"
                if verdict == "dead":
                    dead.append(cid)
                elif verdict == "alive":
                    alive.append(cid)
                else:
                    unknown += 1
                time.sleep(DELAY_SECONDS)

        print(f"dead {len(dead)}, alive {len(alive)}, unverifiable {unknown} (skipped)")

        if not args.apply:
            print("dry run - re-run with --apply to delete the confirmed-dead rows")
            return
        with conn.cursor() as cur:
            if dead:
                cur.execute("DELETE FROM cars WHERE id = ANY(%s)", (dead,))
                print(f"deleted {len(dead)} rows")
            if alive:
                # mark as freshly seen so the next run checks new candidates
                cur.execute("UPDATE cars SET updated_at = now() WHERE id = ANY(%s)", (alive,))
                print(f"re-marked {len(alive)} rows as live")


if __name__ == "__main__":
    main()
