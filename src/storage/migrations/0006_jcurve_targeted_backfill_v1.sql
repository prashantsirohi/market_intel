CREATE TABLE IF NOT EXISTS jcurve_targeted_backfill_run (
    backfill_run_id VARCHAR PRIMARY KEY,
    discovery_run_id VARCHAR NOT NULL,
    cohort_hash VARCHAR NOT NULL,
    requested_from DATE NOT NULL,
    requested_to DATE NOT NULL,
    sources_json VARCHAR NOT NULL,
    chunk_days INTEGER NOT NULL,
    download_selected BOOLEAN NOT NULL,
    status VARCHAR NOT NULL,
    target_count INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL,
    completed_chunk_count INTEGER NOT NULL DEFAULT 0,
    degraded_chunk_count INTEGER NOT NULL DEFAULT 0,
    source_item_count BIGINT NOT NULL DEFAULT 0,
    target_item_count BIGINT NOT NULL DEFAULT 0,
    new_item_count BIGINT NOT NULL DEFAULT 0,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jcurve_targeted_backfill_target (
    backfill_run_id VARCHAR NOT NULL,
    company_id VARCHAR NOT NULL,
    isin VARCHAR,
    nse_symbol VARCHAR,
    bse_code VARCHAR,
    queue_rank INTEGER NOT NULL,
    PRIMARY KEY (backfill_run_id, company_id)
);

CREATE TABLE IF NOT EXISTS jcurve_targeted_backfill_chunk (
    backfill_run_id VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    requested_from DATE NOT NULL,
    requested_to DATE NOT NULL,
    collection_run_id VARCHAR,
    status VARCHAR NOT NULL,
    pages_complete BOOLEAN NOT NULL,
    source_item_count BIGINT NOT NULL,
    target_item_count BIGINT NOT NULL,
    new_item_count BIGINT NOT NULL,
    selected_count BIGINT NOT NULL,
    attachment_eligible_count BIGINT NOT NULL,
    failure_count INTEGER NOT NULL,
    result_json VARCHAR NOT NULL,
    completed_at TIMESTAMP NOT NULL,
    PRIMARY KEY (backfill_run_id, source, requested_from, requested_to)
);
