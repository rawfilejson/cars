-- Database schema. A single `cars` table holds the data from every source

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


CREATE TABLE IF NOT EXISTS cars (
    id              BIGSERIAL PRIMARY KEY,

    source          TEXT        NOT NULL,
    source_id       TEXT        NOT NULL,
    url             TEXT        NOT NULL,

    manufacturer    TEXT,
    model           TEXT,
    year            INTEGER,
    body_type       TEXT,

    price_amount    INTEGER,
    price_currency  TEXT,
    price_with_customs INTEGER,

    engine_volume_l NUMERIC(5,2),
    engine_type     TEXT,
    cylinders       INTEGER,
    power_hp        INTEGER,
    has_turbo       BOOLEAN,
    gearbox         TEXT,
    drive_wheels    TEXT,

    mileage_km      INTEGER,
    color           TEXT,
    doors           INTEGER,
    seats           INTEGER,
    interior_color  TEXT,
    interior_material TEXT,

    steering        TEXT,
    condition       TEXT,
    customs_cleared BOOLEAN,
    has_catalyst    BOOLEAN,
    tech_inspection BOOLEAN,

    vin             VARCHAR(17),
    license_plate   TEXT,

    location        TEXT,
    seller_name     TEXT,
    phone           TEXT,

    posted_date     TEXT,
    views           INTEGER,

    description     TEXT,

    video_url       TEXT,
    image_urls      TEXT[],
    image_keys      TEXT[],

    search_blob     TEXT GENERATED ALWAYS AS (
        lower(
            COALESCE(manufacturer, '') || ' ' ||
            COALESCE(model, '')        || ' ' ||
            COALESCE(description, '')  || ' ' ||
            COALESCE(location, '')     || ' ' ||
            COALESCE(color, '')        || ' ' ||
            COALESCE(body_type, '')    || ' ' ||
            COALESCE(engine_type, '')  || ' ' ||
            COALESCE(year::text, '')   || ' ' ||
            COALESCE(vin::text, '')
        )
    ) STORED,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- set when the source confirms the listing is gone. we keep the row, a sold car
    -- is the most interesting thing a VIN lookup can return
    gone_at         TIMESTAMPTZ,

    CONSTRAINT cars_source_id_unique UNIQUE (source, source_id)
);

-- for databases created before gone_at existed. adding a nullable column is instant
ALTER TABLE cars ADD COLUMN IF NOT EXISTS gone_at TIMESTAMPTZ;

DROP TRIGGER IF EXISTS cars_set_updated_at ON cars;
CREATE TRIGGER cars_set_updated_at
    BEFORE UPDATE ON cars
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS cars_vin_idx ON cars(vin) WHERE vin IS NOT NULL AND vin <> '';
CREATE INDEX IF NOT EXISTS cars_phone_idx ON cars(phone) WHERE phone IS NOT NULL AND phone <> '';
CREATE INDEX IF NOT EXISTS cars_make_model_idx ON cars(manufacturer, model);
CREATE INDEX IF NOT EXISTS cars_year_idx ON cars(year);
CREATE INDEX IF NOT EXISTS cars_price_idx ON cars(price_amount);
CREATE INDEX IF NOT EXISTS cars_updated_at_idx ON cars(updated_at DESC);
-- browse and text search only look at live rows, so index those
CREATE INDEX IF NOT EXISTS cars_live_idx ON cars(updated_at DESC) WHERE gone_at IS NULL;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Careful: adding the generated search_blob column to an existing database is a full table rewrite
-- set `SET statement_timeout = 0;` in the same transaction first.
CREATE INDEX IF NOT EXISTS cars_search_blob_trgm_idx ON cars USING gin (search_blob gin_trgm_ops);
CREATE INDEX IF NOT EXISTS cars_description_trgm_idx ON cars USING gin (description gin_trgm_ops);

-- Phone search runs `LIKE '%suffix'` against the normalised digits
-- a leading wildcard over a function call cannot use a b-tree, so every search would be a full scan
-- this trigram GIN index sits on exactly the expression search.py
-- uses, which removes the scan.

-- On a fresh database the plain CREATE INDEX below is enough: init_db runs schema.sql in one transaction and building on an empty table is instant
-- On a large existing database this form locks the table while it builds, so run it separately instead (outside schema.sql, after init_db) with CONCURRENTLY
-- which cannot live inside a transaction and therefore cannot go here: CREATE INDEX CONCURRENTLY cars_phone_digits_trgm_idx
--     ON cars USING gin (regexp_replace(phone, '\D', '', 'g') gin_trgm_ops)
--     WHERE phone IS NOT NULL AND phone <> '';
CREATE INDEX IF NOT EXISTS cars_phone_digits_trgm_idx
    ON cars USING gin (regexp_replace(phone, '\D', '', 'g') gin_trgm_ops)
    WHERE phone IS NOT NULL AND phone <> '';

-- Rate-limit identity: client_id (the browser's anonymous token) is primary, user_ip is only the backstop
CREATE TABLE IF NOT EXISTS searches (
    id              BIGSERIAL PRIMARY KEY,
    query           TEXT        NOT NULL,
    query_type      TEXT,
    results_count   INTEGER     NOT NULL DEFAULT 0,
    user_ip         INET,
    user_agent      TEXT,
    client_id       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS searches_query_idx ON searches(query);
CREATE INDEX IF NOT EXISTS searches_created_at_idx ON searches(created_at DESC);
CREATE INDEX IF NOT EXISTS searches_client_id_created_idx ON searches (client_id, created_at DESC);
CREATE INDEX IF NOT EXISTS searches_user_ip_created_idx ON searches (user_ip, created_at DESC);

-- With no RLS policies, Supabase's anonymous REST access is closed off.  The backend connects as the owner role, which bypasses RLS, so nothing changes for it
ALTER TABLE cars     ENABLE ROW LEVEL SECURITY;
ALTER TABLE searches ENABLE ROW LEVEL SECURITY;
