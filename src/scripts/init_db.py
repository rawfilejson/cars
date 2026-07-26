# run schema.sql against an empty postgres
#     python -m src.scripts.init_db
# on supabase, neon or any cloud database run this once. with docker the schema
# is applied automatically by the compose entrypoint

from __future__ import annotations

import psycopg

from src.common.config import DATABASE_URL, ROOT_DIR


SCHEMA_PATH = ROOT_DIR / "db" / "schema.sql"


def main() -> None:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"schema.sql not found: {SCHEMA_PATH}")

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    print(f"Schema: {SCHEMA_PATH}")

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()

    print("tables created")


if __name__ == "__main__":
    from src.common.runtime import _configure_windows_runtime

    _configure_windows_runtime()
    main()
