-- Beauty Bridge database schema.
-- Written in portable SQL: runs unchanged on SQLite (development) and
-- PostgreSQL (deployment). Vocabulary checks mirror beautybridge/codebook.py;
-- the Python loader validates the same rules with clearer error messages.

-- ---------------------------------------------------------------------------
-- Products: one row per product, labeled with the codebook
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
    product_id      TEXT PRIMARY KEY,
    brand           TEXT NOT NULL,
    name            TEXT NOT NULL,
    name_ko         TEXT,
    aliases         TEXT,                 -- '|' separated search aliases
    category        TEXT NOT NULL,
    category_group  TEXT NOT NULL,
    shade_family    TEXT,
    finish          TEXT CHECK (finish IN ('matte','soft_matte','satin','dewy','glossy')),
    coverage        TEXT CHECK (coverage IN ('sheer','light','medium','full')),
    texture         TEXT,
    undertone       TEXT CHECK (undertone IN ('cool','neutral','warm')),
    -- intensity labels, integer 0-3 (NULL = not labeled)
    oil_control     INTEGER CHECK (oil_control BETWEEN 0 AND 3),
    hydration       INTEGER CHECK (hydration BETWEEN 0 AND 3),
    blurring        INTEGER CHECK (blurring BETWEEN 0 AND 3),
    shimmer         INTEGER CHECK (shimmer BETWEEN 0 AND 3),
    brightening     INTEGER CHECK (brightening BETWEEN 0 AND 3),
    glow            INTEGER CHECK (glow BETWEEN 0 AND 3),
    longevity       INTEGER CHECK (longevity BETWEEN 0 AND 3),
    volume          INTEGER CHECK (volume BETWEEN 0 AND 3),
    precision       INTEGER CHECK (precision BETWEEN 0 AND 3),
    skin_types      TEXT,                 -- '|' separated
    price           NUMERIC CHECK (price > 0),
    currency        TEXT,
    country_origin  TEXT,
    url             TEXT,
    source          TEXT,
    labeled_by      TEXT,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_products_category ON products (category);
CREATE INDEX IF NOT EXISTS idx_products_brand ON products (brand);

-- ---------------------------------------------------------------------------
-- Beauty goals (definitions also live in data/beauty_goals.json)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS beauty_goals (
    goal_id              TEXT PRIMARY KEY,
    area                 TEXT,              -- skin | eye | lip | contour
    name                 TEXT NOT NULL,
    name_ko              TEXT,
    description          TEXT,
    eligible_categories  TEXT NOT NULL    -- '|' separated
);

CREATE TABLE IF NOT EXISTS goal_criteria (
    goal_id   TEXT NOT NULL REFERENCES beauty_goals (goal_id),
    position  INTEGER NOT NULL,
    type      TEXT NOT NULL CHECK (type IN ('level','one_of')),
    feature   TEXT NOT NULL,
    target    REAL,                       -- for type = level
    vals      TEXT,                       -- for type = one_of, '|' separated
    weight    REAL NOT NULL CHECK (weight > 0),
    PRIMARY KEY (goal_id, position)
);

-- ---------------------------------------------------------------------------
-- Markets: where a product can be bought, at what price, how popular
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_products (
    product_id     TEXT NOT NULL REFERENCES products (product_id),
    market         TEXT NOT NULL,          -- ISO country code: KR, US, JP ...
    availability   TEXT NOT NULL CHECK (availability IN ('none','low','medium','high')),
    local_price    NUMERIC,
    currency       TEXT,
    rating         REAL CHECK (rating BETWEEN 0 AND 5),
    review_count   INTEGER CHECK (review_count >= 0),
    shipping_days  INTEGER CHECK (shipping_days >= 0),
    seller         TEXT,
    observed_at    DATE NOT NULL,
    source         TEXT NOT NULL,
    PRIMARY KEY (product_id, market)
);

-- Every price you ever observe, for price comparison and history charts.
CREATE TABLE IF NOT EXISTS price_observations (
    product_id   TEXT NOT NULL REFERENCES products (product_id),
    market       TEXT NOT NULL,
    seller       TEXT NOT NULL,
    price        NUMERIC NOT NULL CHECK (price > 0),
    shipping     NUMERIC DEFAULT 0,
    currency     TEXT NOT NULL,
    observed_at  DATE NOT NULL,
    source       TEXT NOT NULL,
    PRIMARY KEY (product_id, market, seller, observed_at)
);

-- Ranking chart snapshots (e.g. a weekly best-seller chart).
CREATE TABLE IF NOT EXISTS rankings (
    market      TEXT NOT NULL,
    chart       TEXT NOT NULL,
    date        DATE NOT NULL,
    rank        INTEGER NOT NULL CHECK (rank >= 1),
    product_id  TEXT NOT NULL REFERENCES products (product_id),
    source      TEXT NOT NULL,
    PRIMARY KEY (market, chart, date, rank)
);

-- ---------------------------------------------------------------------------
-- Market intelligence: company financials. source_url is mandatory:
-- every number shown in the dashboard must be traceable (use DART filings).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS company_financials (
    company            TEXT NOT NULL,      -- e.g. 'sephora_korea', 'cj_olive_young'
    fiscal_year        INTEGER NOT NULL,
    basis              TEXT NOT NULL CHECK (basis IN ('separate','consolidated','unspecified')),
    revenue_krw        BIGINT,
    operating_profit_krw BIGINT,           -- negative = operating loss
    net_income_krw     BIGINT,
    store_count        INTEGER,
    source_url         TEXT NOT NULL,
    source_document    TEXT NOT NULL,      -- e.g. '감사보고서 2022, 손익계산서'
    retrieved_at       DATE NOT NULL,
    notes              TEXT,
    PRIMARY KEY (company, fiscal_year, basis)
);

CREATE TABLE IF NOT EXISTS company_events (
    company     TEXT NOT NULL,
    event_date  DATE NOT NULL,             -- first day of the period if not exact
    date_precision TEXT NOT NULL DEFAULT 'day' CHECK (date_precision IN ('day','month','year')),
    event       TEXT NOT NULL,
    event_ko    TEXT,
    source_url  TEXT NOT NULL,
    PRIMARY KEY (company, event_date, event)
);

-- ---------------------------------------------------------------------------
-- First-party reviews written by the site's own users (the live ranking signal)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reviews (
    reviewer_id  TEXT NOT NULL,            -- opaque id, never a name
    product_id   TEXT NOT NULL REFERENCES products (product_id),
    rating       INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    skin_type    TEXT,
    age_band     TEXT CHECK (age_band IN ('10s','20s','30s','40s+')),
    market       TEXT,
    text         TEXT,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (reviewer_id, product_id)
);

-- ---------------------------------------------------------------------------
-- User study: human relevance judgments used to evaluate the models
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS judgments (
    participant_id        TEXT NOT NULL,
    task                  TEXT NOT NULL CHECK (task IN ('similar','would_buy','goal_fit')),
    query_id              TEXT NOT NULL,   -- product_id or goal_id
    candidate_product_id  TEXT NOT NULL REFERENCES products (product_id),
    relevance             INTEGER NOT NULL CHECK (relevance BETWEEN 0 AND 3),
    judged_at             DATE,
    PRIMARY KEY (participant_id, task, query_id, candidate_product_id)
);
