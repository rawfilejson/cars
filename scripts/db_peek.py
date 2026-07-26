# quick look at the database: row counts, a few sample rows, phone formats
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
            print("cars by source")
            cur.execute("""
                SELECT source, COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE vin <> '') AS with_vin,
                       COUNT(*) FILTER (WHERE phone <> '') AS with_phone,
                       COUNT(*) FILTER (WHERE image_urls IS NOT NULL AND array_length(image_urls, 1) > 0) AS with_photos
                FROM cars GROUP BY source ORDER BY source
            """)
            for r in cur.fetchall():
                print(f"  {r['source']} total={r['total']} vin={r['with_vin']} "
                      f"phone={r['with_phone']} photos={r['with_photos']}")

            print("\nlatest autopapa cars")
            cur.execute("""
                SELECT source_id, manufacturer, model, year, price_amount, price_currency,
                       mileage_km, engine_volume_l, engine_type, location, phone, vin,
                       array_length(image_urls, 1) AS photo_count
                FROM cars WHERE source = 'autopapa'
                ORDER BY updated_at DESC LIMIT 3
            """)
            for r in cur.fetchall():
                print(f"  {r['source_id']} {r['year']} {r['manufacturer']} {r['model']} "
                      f"{r['price_amount']} {r['price_currency']} {r['mileage_km']}km "
                      f"{r['engine_volume_l']}L {r['engine_type']} {r['location']} "
                      f"vin={r['vin'] or '-'} phone={r['phone'] or '-'} "
                      f"photos={r['photo_count'] or 0}")

            print("\nmost common phone formats")
            cur.execute("""
                SELECT phone, COUNT(*) AS n
                FROM cars
                WHERE phone <> ''
                GROUP BY phone
                ORDER BY COUNT(*) DESC
                LIMIT 10
            """)
            for r in cur.fetchall():
                print(f"  {r['phone']} x{r['n']}")

            cur.execute("""
                SELECT
                  COUNT(*) FILTER (WHERE phone LIKE '%% %%' AND phone <> '') AS spaced_format,
                  COUNT(*) FILTER (WHERE phone NOT LIKE '%% %%' AND phone <> '') AS joined_format,
                  COUNT(*) FILTER (WHERE phone = '') AS empty_phone,
                  COUNT(*) AS total
                FROM cars
            """)
            r = cur.fetchone()
            print(f"\nspaced={r['spaced_format']} joined={r['joined_format']} "
                  f"empty={r['empty_phone']} total={r['total']}")


if __name__ == "__main__":
    main()
