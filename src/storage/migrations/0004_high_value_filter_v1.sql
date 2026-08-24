CREATE SEQUENCE IF NOT EXISTS announcement_filter_decision_seq;

CREATE TABLE IF NOT EXISTS announcement_collection_run (
    collection_run_id VARCHAR PRIMARY KEY,
    source VARCHAR NOT NULL,
    requested_from TIMESTAMP,
    requested_to TIMESTAMP,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    status VARCHAR NOT NULL,
    page_count INTEGER NOT NULL DEFAULT 0,
    pages_complete BOOLEAN NOT NULL DEFAULT FALSE,
    item_count INTEGER NOT NULL DEFAULT 0,
    new_count INTEGER NOT NULL DEFAULT 0,
    selected_count INTEGER NOT NULL DEFAULT 0,
    attachment_eligible_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    response_hashes_json VARCHAR NOT NULL DEFAULT '[]',
    failures_json VARCHAR NOT NULL DEFAULT '[]',
    summary_json VARCHAR NOT NULL DEFAULT '{}',
    policy_version VARCHAR NOT NULL,
    policy_hash VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS announcement_filter_decision (
    decision_id BIGINT PRIMARY KEY DEFAULT nextval('announcement_filter_decision_seq'),
    collection_run_id VARCHAR NOT NULL,
    announcement_key VARCHAR NOT NULL,
    raw_event_id BIGINT,
    source VARCHAR NOT NULL,
    external_id VARCHAR,
    symbol VARCHAR,
    subject VARCHAR,
    details VARCHAR,
    attachment_url VARCHAR,
    attachment_filename VARCHAR,
    decision VARCHAR NOT NULL,
    attachment_eligible BOOLEAN NOT NULL,
    reason_codes_json VARCHAR NOT NULL,
    matched_signals_json VARCHAR NOT NULL,
    policy_version VARCHAR NOT NULL,
    policy_hash VARCHAR NOT NULL,
    decided_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE(collection_run_id, announcement_key, policy_version)
);

CREATE INDEX IF NOT EXISTS idx_announcement_filter_decision_raw
    ON announcement_filter_decision(raw_event_id);
CREATE INDEX IF NOT EXISTS idx_announcement_filter_decision_policy
    ON announcement_filter_decision(policy_version, decision);
