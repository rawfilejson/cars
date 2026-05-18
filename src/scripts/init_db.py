"""
ბაზის ინიციალიზაცია — schema.sql-ის გაშვება ცარიელ PostgreSQL-ზე.

გამოყენება:
    python -m src.scripts.init_db

Supabase / Neon / cloud DB-ში schema უნდა გაუშვა ერთხელ. Docker-ის შემთხვევაში
schema.sql ავტომატურად იდგმება docker-compose-ის entrypoint-ით.
"""

from __future__ import annotations

import psycopg

from src.common.config import DATABASE_URL, ROOT_DIR


SCHEMA_PATH = ROOT_DIR / "db" / "schema.sql"


def main() -> None:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"schema.sql ვერ ვიპოვე: {SCHEMA_PATH}")

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    print(f"Schema: {SCHEMA_PATH}")

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()

    print("ცხრილები შექმნილია.")


if __name__ == "__main__":
    # Windows-ზე UTF-8 stdout-ის გასაშვებად
    from src.common.runtime import _configure_windows_runtime

    _configure_windows_runtime()
    main()
