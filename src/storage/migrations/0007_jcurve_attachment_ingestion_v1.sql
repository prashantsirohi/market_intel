CREATE TABLE IF NOT EXISTS jcurve_attachment_ingestion_run (
    attachment_run_id VARCHAR PRIMARY KEY,
    parent_backfill_run_id VARCHAR NOT NULL,
    policy_version VARCHAR NOT NULL,
    policy_hash VARCHAR NOT NULL,
    candidate_hash VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    candidate_count INTEGER NOT NULL,
    completed_count INTEGER NOT NULL DEFAULT 0,
    valid_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jcurve_attachment_ingestion_item (
    attachment_run_id VARCHAR NOT NULL,
    raw_event_id BIGINT NOT NULL,
    source VARCHAR NOT NULL,
    attachment_url VARCHAR NOT NULL,
    matched_signals_json VARCHAR NOT NULL,
    selection_reason VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    document_id BIGINT,
    content_hash VARCHAR,
    file_size BIGINT,
    error_message VARCHAR,
    completed_at TIMESTAMP NOT NULL,
    PRIMARY KEY (attachment_run_id, raw_event_id)
);

CREATE INDEX IF NOT EXISTS idx_jcurve_attachment_parent
    ON jcurve_attachment_ingestion_run(parent_backfill_run_id, status);

CREATE INDEX IF NOT EXISTS idx_jcurve_attachment_item_status
    ON jcurve_attachment_ingestion_item(attachment_run_id, status);
