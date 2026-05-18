-- =====================================================================
-- მანქანების ბაზის სქემა
-- ===================================================================== --
-- მთავარი იდეა: ერთი ცხრილი `cars` ინახავს ყველაფერს ყველა წყაროდან.
-- (source, source_id) წყვილი არის ბუნებრივი იდენტიფიკატორი — autopapa-ს
-- მანქანის #940645 და myauto-ს #940645 სხვადასხვა მანქანებია.
-- =====================================================================

-- ფუნქცია updated_at ავტომატური განახლებისთვის
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


CREATE TABLE IF NOT EXISTS cars (
    -- შიდა იდენტიფიკატორი (ბაზის გასაღები)
    id              BIGSERIAL PRIMARY KEY,

    -- წყაროს იდენტიფიკაცია — ეს ორი ერთად უნდა იყოს უნიკალური
    source          TEXT        NOT NULL,           -- "autopapa" | "myauto"
    source_id       TEXT        NOT NULL,           -- მანქანის id წყაროზე
    url             TEXT        NOT NULL,

    -- ძირითადი ინფორმაცია
    manufacturer    TEXT,
    model           TEXT,
    year            INTEGER,
    body_type       TEXT,

    -- ფასი
    price_amount    INTEGER,                        -- რიცხვი (გარეშე სიმბოლოებისა)
    price_currency  TEXT,                           -- "USD" | "EUR" | "GEL"
    price_with_customs INTEGER,                     -- ფასი ლარში განბაჟებით

    -- ძრავა და ტრანსმისია
    engine_volume_l NUMERIC(5,2),                   -- ლიტრებში, მაგ: 2.5 (ცუდი მონაცემები source-ში ხანდახან 1000+, ამიტომ ფართო ფორმატი)
    engine_type     TEXT,                           -- ბენზინი/დიზელი/ჰიბრიდი/...
    cylinders       INTEGER,
    power_hp        INTEGER,
    has_turbo       BOOLEAN,
    gearbox         TEXT,                           -- ავტომატიკა/მექანიკა/...
    drive_wheels    TEXT,                           -- წინა/უკანა/4x4

    -- გარბენი და გარეგნობა
    mileage_km      INTEGER,
    color           TEXT,
    doors           INTEGER,
    seats           INTEGER,
    interior_color  TEXT,
    interior_material TEXT,

    -- სხვა
    steering        TEXT,                           -- "მარცხენა" | "მარჯვენა"
    condition       TEXT,
    customs_cleared BOOLEAN,                        -- TRUE = განბაჟებული
    has_catalyst    BOOLEAN,
    tech_inspection BOOLEAN,

    -- იდენტიფიკატორები
    vin             VARCHAR(17),                    -- ყოველთვის დიდი ასოებით
    license_plate   TEXT,

    -- კონტაქტი
    location        TEXT,
    seller_name     TEXT,
    phone           TEXT,                           -- +-ით იწყება ყოველთვის

    -- მეტა-ინფორმაცია
    posted_date     TEXT,                           -- წყაროზე როგორ წერია, ისე
    views           INTEGER,

    -- შინაარსი
    description     TEXT,

    -- მედია
    video_url       TEXT,
    image_urls      TEXT[],                         -- ფოტოების URL-ების მასივი (წყაროზე)
    image_keys      TEXT[],                         -- R2-ში ფოტოების key-ები (uploaded)

    -- დროის შტამპები
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- უნიკალურობის შეზღუდვა
    CONSTRAINT cars_source_id_unique UNIQUE (source, source_id)
);

-- updated_at-ის ავტომატური განახლება
DROP TRIGGER IF EXISTS cars_set_updated_at ON cars;
CREATE TRIGGER cars_set_updated_at
    BEFORE UPDATE ON cars
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- =====================================================================
-- ინდექსები — ძიება სწრაფი იყოს
-- =====================================================================

-- ვინ-ით ძიება (მთავარი feature ვებსაიტისთვის)
CREATE INDEX IF NOT EXISTS cars_vin_idx ON cars(vin) WHERE vin IS NOT NULL AND vin <> '';

-- ნომრით ძიება
CREATE INDEX IF NOT EXISTS cars_phone_idx ON cars(phone) WHERE phone IS NOT NULL AND phone <> '';

-- მწარმოებელი + მოდელით ფილტრაცია
CREATE INDEX IF NOT EXISTS cars_make_model_idx ON cars(manufacturer, model);

-- წლის შუალედი
CREATE INDEX IF NOT EXISTS cars_year_idx ON cars(year);

-- ფასი
CREATE INDEX IF NOT EXISTS cars_price_idx ON cars(price_amount);

-- ბოლოს განახლებული — სორტირებისთვის
CREATE INDEX IF NOT EXISTS cars_updated_at_idx ON cars(updated_at DESC);

-- =====================================================================
-- სრულტექსტური ძიება (description-ში)
-- =====================================================================
-- pg_trgm extension — fuzzy/partial match-ისთვის (მაგ: "ბმვ" → BMW)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS cars_description_trgm_idx ON cars USING gin (description gin_trgm_ops);

-- =====================================================================
-- ვებსაიტის search-ის ისტორია (მომავლისთვის)
-- =====================================================================
-- ვინც დასერჩა, რა შეიყვანა, რა მოვიდა შედეგად
CREATE TABLE IF NOT EXISTS searches (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID,                           -- NULL თუ ანონიმური
    query           TEXT        NOT NULL,
    query_type      TEXT,                           -- "vin" | "phone" | "free_text"
    results_count   INTEGER     NOT NULL DEFAULT 0,
    paid            BOOLEAN     NOT NULL DEFAULT FALSE,
    paid_amount     NUMERIC(10,2),
    user_ip         INET,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS searches_query_idx ON searches(query);
CREATE INDEX IF NOT EXISTS searches_created_at_idx ON searches(created_at DESC);
CREATE INDEX IF NOT EXISTS searches_user_id_idx ON searches(user_id);
CREATE INDEX IF NOT EXISTS searches_user_ip_idx ON searches(user_ip);

-- =====================================================================
-- მომხმარებლის subscription-ი
-- =====================================================================
-- Supabase Auth-ში user-ი ცალკე ცხრილია (auth.users). აქ ვინახავთ მხოლოდ
-- subscription-ის სტატუსს — ვის გადახდილი აქვს, რომელ თვემდე.
CREATE TABLE IF NOT EXISTS subscriptions (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID        NOT NULL UNIQUE,    -- მიუთითებს auth.users.id-ზე
    status          TEXT        NOT NULL,           -- "active" | "expired" | "canceled"
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    payment_method  TEXT,                           -- "bog" | "tbc" | "stripe"
    last_payment_amount NUMERIC(10,2),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS subscriptions_user_id_idx ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS subscriptions_expires_at_idx ON subscriptions(expires_at);

DROP TRIGGER IF EXISTS subscriptions_set_updated_at ON subscriptions;
CREATE TRIGGER subscriptions_set_updated_at
    BEFORE UPDATE ON subscriptions
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- =====================================================================
-- ფოტო-VIN OCR შედეგები
-- =====================================================================
-- ფოტოს VIN OCR-ით ვცდილობთ ვინ-ის ამოღებას. შედეგებს ცალკე ცხრილში ვინახავთ,
-- რომ მერე გადავამოწმოთ partial VIN-ის შესაბამისობა და human review.
CREATE TABLE IF NOT EXISTS photo_vin_ocr (
    id              BIGSERIAL PRIMARY KEY,
    car_id          BIGINT      NOT NULL REFERENCES cars(id) ON DELETE CASCADE,
    image_key       TEXT        NOT NULL,
    extracted_vin   VARCHAR(17),
    confidence      NUMERIC(4,3),                   -- 0.000 — 1.000
    matches_partial BOOLEAN,                        -- partial VIN-ს ემთხვევა?
    needs_review    BOOLEAN     NOT NULL DEFAULT FALSE,
    ocr_provider    TEXT,                           -- "google_vision" | "tesseract"
    raw_response    JSONB,                          -- სრული OCR პასუხი — debug-ისთვის
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS photo_vin_ocr_car_id_idx ON photo_vin_ocr(car_id);
CREATE INDEX IF NOT EXISTS photo_vin_ocr_needs_review_idx ON photo_vin_ocr(needs_review)
    WHERE needs_review = TRUE;

-- =====================================================================
-- Row Level Security (RLS) — default deny all
-- =====================================================================
-- Supabase ცხრილებს ავტომატურად ანახებს REST API-ით ანონიმური მომხმარებლებისთვის.
-- ჩავრთოთ RLS რომ ანონიმური წვდომა დაიხუროს. ჩვენი backend პირდაპირ DB-სთან
-- მუშაობს postgres user-ით (RLS bypass), ვებსაიტი კი მერე ცალკეულ პოლიტიკებს
-- დაამატებს უფლებამოსილი მომხმარებლებისთვის.
ALTER TABLE cars          ENABLE ROW LEVEL SECURITY;
ALTER TABLE searches      ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE photo_vin_ocr ENABLE ROW LEVEL SECURITY;
