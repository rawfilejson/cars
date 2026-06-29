"""One-off backfill: recover VIN and phone from a listing's description
when the structured field is empty.

New listings already get this during scraping; this applies the same tested
extractors (src.common.vin.find_vin / src.common.normalize.phone_from_text)
to rows already in the database.

Usage (dry run prints counts, writes nothing):

    DATABASE_URL=postgresql://... uv run python scripts/backfill_contacts.py

Add --apply to write the updates:

    DATABASE_URL=postgresql://... uv run python scripts/backfill_contacts.py --apply
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402

from src.common.normalize import phone_from_text  # noqa: E402
from src.common.vin import find_vin  # noqa: E402


PAGE = 3000


def main() -> None:
    apply = "--apply" in sys.argv
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("set DATABASE_URL to the Postgres connection string")

    vin_found = phone_found = scanned = updated = 0
    last_id = 0

    # autocommit so each page commits as it goes (resumable) and SET applies
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '120s'")

        while True:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, vin, phone, description
                    FROM cars
                    WHERE id > %s
                      AND description IS NOT NULL AND description <> ''
                      AND ((vin IS NULL OR vin = '') OR (phone IS NULL OR phone = ''))
                    ORDER BY id
                    LIMIT %s
                    """,
                    (last_id, PAGE),
                )
                rows = cur.fetchall()

            if not rows:
                break

            page_updates: list[tuple[str | None, str | None, int]] = []
            for cid, vin, phone, desc in rows:
                last_id = cid
                scanned += 1
                new_vin, new_phone = vin, phone
                if not vin:
                    v = find_vin(desc)
                    if v:
                        new_vin = v
                        vin_found += 1
                if not phone:
                    p = phone_from_text(desc)
                    if p:
                        new_phone = p
                        phone_found += 1
                if new_vin != vin or new_phone != phone:
                    page_updates.append((new_vin, new_phone, cid))

            if apply and page_updates:
                vins = [u[0] for u in page_updates]
                phones = [u[1] for u in page_updates]
                ids = [u[2] for u in page_updates]
                # one round-trip per page: COALESCE keeps any existing value
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE cars AS c
                        SET vin   = COALESCE(v.vin, c.vin),
                            phone = COALESCE(v.phone, c.phone)
                        FROM unnest(%s::bigint[], %s::varchar[], %s::text[])
                             AS v(id, vin, phone)
                        WHERE c.id = v.id
                        """,
                        (ids, vins, phones),
                    )
                updated += len(page_updates)

            tail = f", updated {updated}" if apply else ""
            print(f"  scanned {scanned} | vin {vin_found} | phone {phone_found}{tail}")

    print(f"\nscanned {scanned} rows missing a VIN or phone")
    print(f"  VINs recoverable:   {vin_found}")
    print(f"  phones recoverable: {phone_found}")
    if apply:
        print(f"  rows updated:       {updated}")
    else:
        print("dry run — re-run with --apply to write")


if __name__ == "__main__":
    main()
