# mark listings the source site has deleted a row untouched for --days is only a candidate, the scrapers skip rows they already have so every candidate is checked against the source and only confirmed deletions get marked
# anything we cannot check is left alone
# the row stays, it just gets a gone_at date. browse and text search hide it, a VIN or phone lookup still finds it, which is the whole point of keeping an archive dry run by default, --apply writes

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
    # 'alive' | 'dead' | 'unknown' for a myauto listing
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
    # myauto status: 1 = active
    if status is not None and status != 1:
        return "dead"
    return "alive"


def check_autopapa(client: httpx.Client, url: str) -> str:
    try:
        r = client.get(url, timeout=15, follow_redirects=True)
    except Exception:
        return "unknown"
    if r.status_code in (404, 410):
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

        dead = []
        alive = []
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
            print("dry run, use --apply to write")
            return
        with conn.cursor() as cur:
            if dead:
                cur.execute(
                    "UPDATE cars SET gone_at = now() WHERE id = ANY(%s) AND gone_at IS NULL",
                    (dead,),
                )
                print(f"marked {len(dead)} rows gone")
            if alive:
                # bump so the next run moves on to other candidates, and un-mark anything that came back
                cur.execute(
                    "UPDATE cars SET updated_at = now(), gone_at = NULL WHERE id = ANY(%s)",
                    (alive,),
                )


if __name__ == "__main__":
    main()
