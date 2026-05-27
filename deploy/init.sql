-- TimescaleDB schema for badi occupancy data.
-- Runs automatically when the postgres container first starts (empty data dir).

-- ── Raw readings hypertable ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS occupancy (
    ts                  TIMESTAMPTZ NOT NULL,
    occupancy_oerlikon  INTEGER,
    occupancy_city      INTEGER
);

SELECT create_hypertable(
    'occupancy', 'ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- Index on individual locations for dashboard queries
CREATE INDEX IF NOT EXISTS idx_occ_oerlikon ON occupancy (ts) WHERE occupancy_oerlikon IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_occ_city     ON occupancy (ts) WHERE occupancy_city IS NOT NULL;

-- ── Continuous aggregate: per-weekday × 15-min slot ──────────────────────────
-- Replaces the Python aggregator.py loop. TimescaleDB refreshes this hourly.

CREATE MATERIALIZED VIEW IF NOT EXISTS occupancy_15min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('15 minutes', ts)   AS bucket,
    EXTRACT(DOW FROM ts)::int       AS dow,
    AVG(occupancy_oerlikon)         AS avg_oerlikon,
    STDDEV(occupancy_oerlikon)      AS std_oerlikon,
    COUNT(occupancy_oerlikon)       AS cnt_oerlikon,
    AVG(occupancy_city)             AS avg_city,
    STDDEV(occupancy_city)          AS std_city,
    COUNT(occupancy_city)           AS cnt_city
FROM occupancy
GROUP BY bucket, dow
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'occupancy_15min',
    start_offset      => INTERVAL '90 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE
);

-- ── Compression policy ───────────────────────────────────────────────────────
-- Compress chunks older than 7 days. ~21k rows/day at 2 int columns → trivial.

SELECT add_compression_policy(
    'occupancy',
    INTERVAL '7 days',
    if_not_exists => TRUE
);

-- ── Write optimisation ───────────────────────────────────────────────────────
-- Tolerate losing ~200ms of readings on a hard crash (power outage).
-- For occupancy data this is fully acceptable.

ALTER SYSTEM SET synchronous_commit = 'off';
SELECT pg_reload_conf();
