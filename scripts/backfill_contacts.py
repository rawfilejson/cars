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


BATCH = 1000


def main() -> None:
    apply = "--apply" in sys.argv
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("set DATABASE_URL to the Postgres connection string")

    vin_found = phone_found = scanned = 0
    updates: list[tuple[str | None, str | None, int]] = []

    with psycopg.connect(dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, vin, phone, description
                FROM cars
                WHERE description IS NOT NULL AND description <> ''
                  AND ((vin IS NULL OR vin = '') OR (phone IS NULL OR phone = ''))
                """
            )
            rows = cur.fetchall()

        for cid, vin, phone, desc in rows:
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
                updates.append((new_vin, new_phone, cid))

        print(f"scanned {scanned} rows missing a VIN or phone")
        print(f"  VINs recoverable:   {vin_found}")
        print(f"  phones recoverable: {phone_found}")
        print(f"  rows to update:     {len(updates)}")

        if not apply:
            print("dry run — re-run with --apply to write")
            return

        with conn.cursor() as cur:
            for i in range(0, len(updates), BATCH):
                cur.executemany(
                    "UPDATE cars SET vin = %s, phone = %s WHERE id = %s",
                    updates[i:i + BATCH],
                )
                conn.commit()
                print(f"  committed {min(i + BATCH, len(updates))}/{len(updates)}")
    print("done")


if __name__ == "__main__":
    main()
