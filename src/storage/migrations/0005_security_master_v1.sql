CREATE SEQUENCE IF NOT EXISTS listing_observation_seq;

CREATE TABLE IF NOT EXISTS listing_sync_run (
    sync_run_id VARCHAR PRIMARY KEY,
    exchange VARCHAR NOT NULL,
    effective_date DATE NOT NULL,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    status VARCHAR NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    valid_isin_count INTEGER NOT NULL DEFAULT 0,
    invalid_isin_count INTEGER NOT NULL DEFAULT 0,
    duplicate_key_count INTEGER NOT NULL DEFAULT 0,
    source_url VARCHAR NOT NULL,
    source_hash VARCHAR,
    parser_version VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL,
    temporal_trust VARCHAR NOT NULL DEFAULT 'LATEST_ONLY_OBSERVED_AT_SYNC',
    error_code VARCHAR,
    error_message VARCHAR,
    summary_json VARCHAR NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS listed_security_observation (
    observation_id BIGINT PRIMARY KEY DEFAULT nextval('listing_observation_seq'),
    sync_run_id VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    exchange_security_id VARCHAR NOT NULL,
    symbol VARCHAR,
    isin VARCHAR,
    company_name VARCHAR,
    series VARCHAR,
    board VARCHAR,
    listing_date DATE,
    active_flag BOOLEAN NOT NULL,
    instrument_type VARCHAR NOT NULL,
    identity_status VARCHAR NOT NULL,
    source_row_hash VARCHAR NOT NULL,
    observed_at TIMESTAMP NOT NULL,
    UNIQUE(sync_run_id, exchange, exchange_security_id)
);

CREATE INDEX IF NOT EXISTS idx_listing_observation_isin
    ON listed_security_observation(isin);
CREATE INDEX IF NOT EXISTS idx_listing_observation_exchange_id
    ON listed_security_observation(exchange, exchange_security_id);

ALTER TABLE announcement_filter_decision ADD COLUMN IF NOT EXISTS isin VARCHAR;
ALTER TABLE announcement_filter_decision ADD COLUMN IF NOT EXISTS listing_membership VARCHAR;
ALTER TABLE announcement_filter_decision ADD COLUMN IF NOT EXISTS exchange_security_id VARCHAR;

CREATE OR REPLACE VIEW listed_security_current AS
WITH ranked_runs AS (
    SELECT sync_run_id, exchange,
           row_number() OVER (
               PARTITION BY exchange
               ORDER BY effective_date DESC, completed_at DESC, sync_run_id DESC
           ) AS ordinal
    FROM listing_sync_run
    WHERE status = 'COMPLETED'
), latest_runs AS (
    SELECT sync_run_id, exchange FROM ranked_runs WHERE ordinal = 1
)
SELECT observation.*
FROM listed_security_observation observation
JOIN latest_runs latest
  ON latest.sync_run_id = observation.sync_run_id
 AND latest.exchange = observation.exchange;

CREATE OR REPLACE VIEW security_listing_membership_current AS
SELECT
    isin,
    max(CASE WHEN exchange = 'NSE' THEN symbol END) AS nse_symbol,
    max(CASE WHEN exchange = 'BSE' THEN symbol END) AS bse_symbol,
    max(CASE WHEN exchange = 'BSE' THEN exchange_security_id END) AS bse_code,
    max(company_name) AS company_name,
    count(DISTINCT exchange) AS exchange_count,
    CASE
        WHEN count(DISTINCT exchange) = 2 THEN 'DUAL'
        WHEN max(CASE WHEN exchange = 'NSE' THEN 1 ELSE 0 END) = 1 THEN 'NSE_ONLY'
        WHEN max(CASE WHEN exchange = 'BSE' THEN 1 ELSE 0 END) = 1 THEN 'BSE_ONLY'
        ELSE 'UNRESOLVED'
    END AS listing_membership,
    count(*) AS listing_row_count,
    CASE
        WHEN count(DISTINCT CASE WHEN exchange = 'NSE' THEN exchange_security_id END) > 1
          OR count(DISTINCT CASE WHEN exchange = 'BSE' THEN exchange_security_id END) > 1
        THEN 'AMBIGUOUS'
        ELSE 'RESOLVED'
    END AS identity_status
FROM listed_security_current
WHERE active_flag = TRUE
  AND identity_status = 'VALID_ISIN'
  AND instrument_type = 'CORPORATE_EQUITY'
GROUP BY isin;
