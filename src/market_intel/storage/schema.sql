-- market_intel DuckDB schema (DuckDB-native syntax with sequences)

CREATE SEQUENCE IF NOT EXISTS tracked_entity_seq;
CREATE SEQUENCE IF NOT EXISTS raw_event_seq;
CREATE SEQUENCE IF NOT EXISTS resolved_event_seq;
CREATE SEQUENCE IF NOT EXISTS filing_document_seq;
CREATE SEQUENCE IF NOT EXISTS alert_log_seq;

CREATE TABLE IF NOT EXISTS tracked_entity (
    entity_id BIGINT PRIMARY KEY DEFAULT nextval('tracked_entity_seq'),
    symbol VARCHAR NOT NULL,
    isin VARCHAR,
    company_name VARCHAR,
    entity_type VARCHAR NOT NULL DEFAULT 'stock',
    sector VARCHAR,
    source_list VARCHAR,
    priority INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    aliases_json VARCHAR,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE(symbol)
);

CREATE TABLE IF NOT EXISTS raw_event (
    raw_event_id BIGINT PRIMARY KEY DEFAULT nextval('raw_event_seq'),
    source VARCHAR NOT NULL,
    source_type VARCHAR NOT NULL,
    external_id VARCHAR,
    symbol VARCHAR,
    isin VARCHAR,
    company_name VARCHAR,
    title VARCHAR,
    category_desc VARCHAR,
    event_date TIMESTAMP,
    published_at TIMESTAMP,
    link VARCHAR,
    attachment_url VARCHAR,
    description VARCHAR,
    raw_payload_json VARCHAR NOT NULL,
    event_hash VARCHAR NOT NULL,
    ingested_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    seen_count INTEGER NOT NULL DEFAULT 1,
    processing_status VARCHAR NOT NULL DEFAULT 'new',
    status VARCHAR NOT NULL DEFAULT 'pending',
    error_message VARCHAR,
    UNIQUE(event_hash)
);

CREATE TABLE IF NOT EXISTS resolved_event (
    resolved_event_id BIGINT PRIMARY KEY DEFAULT nextval('resolved_event_seq'),
    raw_event_id BIGINT NOT NULL,
    entity_id BIGINT,
    primary_category VARCHAR,
    secondary_category VARCHAR,
    sentiment_label VARCHAR,
    sentiment_score DOUBLE,
    importance_score DOUBLE,
    trust_score DOUBLE,
    parser_confidence DOUBLE,
    novelty_score DOUBLE,
    alert_level VARCHAR,
    is_official BOOLEAN,
    summary_text VARCHAR,
    key_facts_json VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'pending',
    resolved_at TIMESTAMP,
    acknowledged_at TIMESTAMP,
    UNIQUE(raw_event_id)
);

CREATE TABLE IF NOT EXISTS filing_document (
    document_id BIGINT PRIMARY KEY DEFAULT nextval('filing_document_seq'),
    raw_event_id BIGINT NOT NULL,
    source_url VARCHAR NOT NULL,
    local_path VARCHAR,
    mime_type VARCHAR,
    file_hash VARCHAR,
    file_size BIGINT DEFAULT 0,
    download_status VARCHAR NOT NULL DEFAULT 'pending',
    extraction_status VARCHAR NOT NULL DEFAULT 'pending',
    download_attempts INTEGER NOT NULL DEFAULT 0,
    downloaded_at TIMESTAMP,
    extracted_at TIMESTAMP,
    extracted_text VARCHAR,
    error_message VARCHAR,
    UNIQUE(source_url)
);

CREATE TABLE IF NOT EXISTS alert_log (
    alert_id BIGINT PRIMARY KEY DEFAULT nextval('alert_log_seq'),
    resolved_event_id BIGINT NOT NULL,
    channel VARCHAR NOT NULL,
    alert_status VARCHAR NOT NULL,
    priority VARCHAR NOT NULL DEFAULT 'normal',
    sent_at TIMESTAMP,
    acknowledged_at TIMESTAMP,
    payload_json VARCHAR,
    UNIQUE(resolved_event_id, channel)
);

CREATE INDEX IF NOT EXISTS idx_tracked_entity_active ON tracked_entity(is_active);
CREATE INDEX IF NOT EXISTS idx_raw_event_symbol ON raw_event(symbol);
CREATE INDEX IF NOT EXISTS idx_raw_event_event_date ON raw_event(event_date);
CREATE INDEX IF NOT EXISTS idx_raw_event_status ON raw_event(processing_status);
CREATE INDEX IF NOT EXISTS idx_raw_event_hash_seen ON raw_event(event_hash, seen_count);
CREATE INDEX IF NOT EXISTS idx_resolved_event_entity_id ON resolved_event(entity_id);
CREATE INDEX IF NOT EXISTS idx_resolved_event_alert_level ON resolved_event(alert_level);
CREATE INDEX IF NOT EXISTS idx_resolved_event_status ON resolved_event(status);
CREATE INDEX IF NOT EXISTS idx_filing_document_raw_event_id ON filing_document(raw_event_id);
CREATE INDEX IF NOT EXISTS idx_alert_log_event_id ON alert_log(resolved_event_id);