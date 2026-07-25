# ბაზის სწრაფი გადახედვა — count-ი, sample row-ები, phone ფორმატები.
from __future__ import annotations

import sys

import psycopg
from psycopg.rows import dict_row

from src.common.config import DATABASE_URL


if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            print("=" * 70)
            print("CARS BY SOURCE")
            print("=" * 70)
            cur.execute("""
                SELECT source, COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE vin <> '') AS with_vin,
                       COUNT(*) FILTER (WHERE phone <> '') AS with_phone,
                       COUNT(*) FILTER (WHERE image_urls IS NOT NULL AND array_length(image_urls, 1) > 0) AS with_photos
                FROM cars GROUP BY source ORDER BY source
            """)
            for row in cur.fetchall():
                print(f"  {row['source']:10s}  total:{row['total']:6d}  "
                      f"vin:{row['with_vin']:5d}  phone:{row['with_phone']:5d}  "
                      f"photos:{row['with_photos']:5d}")

            print("\n" + "=" * 70)
            print("SAMPLE: autopapa, 3 latest cars")
            print("=" * 70)
            cur.execute("""
                SELECT source_id, manufacturer, model, year, price_amount, price_currency,
                       mileage_km, engine_volume_l, engine_type, location, phone, vin,
                       array_length(image_urls, 1) AS photo_count
                FROM cars WHERE source = 'autopapa'
                ORDER BY updated_at DESC LIMIT 3
            """)
            for row in cur.fetchall():
                print(f"\n  source_id:    {row['source_id']}")
                print(f"  car:          {row['year']} {row['manufacturer']} {row['model']}")
                print(f"  price:        {row['price_amount']} {row['price_currency']}")
                print(f"  mileage:      {row['mileage_km']} km")
                print(f"  engine:       {row['engine_volume_l']} L, {row['engine_type']}")
                print(f"  location:     {row['location']}")
                print(f"  phone:        {row['phone'] or '(empty)'}")
                print(f"  vin:          {row['vin'] or '(none)'}")
                print(f"  photos:       {row['photo_count'] or 0}")

            print("\n" + "=" * 70)
            print("PHONE FORMATS — sample of distinct patterns")
            print("=" * 70)
            cur.execute("""
                SELECT phone, COUNT(*) AS n
                FROM cars
                WHERE phone <> ''
                GROUP BY phone
                ORDER BY COUNT(*) DESC
                LIMIT 10
            """)
            for row in cur.fetchall():
                print(f"  {row['phone']:25s}  ×{row['n']}")

            print("\n" + "=" * 70)
            print("PHONE FORMAT STATS — joined vs spaced")
            print("=" * 70)
            cur.execute("""
                SELECT
                  COUNT(*) FILTER (WHERE phone LIKE '%% %%' AND phone <> '') AS spaced_format,
                  COUNT(*) FILTER (WHERE phone NOT LIKE '%% %%' AND phone <> '') AS joined_format,
                  COUNT(*) FILTER (WHERE phone = '') AS empty_phone,
                  COUNT(*) AS total
                FROM cars
            """)
            row = cur.fetchone()
            print(f"  spaced  (\"+995 595 515 141\"):  {row['spaced_format']}")
            print(f"  joined  (\"+995595515141\"):     {row['joined_format']}")
            print(f"  empty:                          {row['empty_phone']}")
            print(f"  total:                          {row['total']}")


if __name__ == "__main__":
    main()
