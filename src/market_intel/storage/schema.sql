-- market_intel DuckDB schema v2.0
-- NSE Corporate Filings Intelligence System

-- Sequences
CREATE SEQUENCE IF NOT EXISTS tracked_entity_seq;
CREATE SEQUENCE IF NOT EXISTS raw_event_seq;
CREATE SEQUENCE IF NOT EXISTS resolved_event_seq;
CREATE SEQUENCE IF NOT EXISTS filing_document_seq;
CREATE SEQUENCE IF NOT EXISTS alert_log_seq;
CREATE SEQUENCE IF NOT EXISTS llm_insight_seq;
CREATE SEQUENCE IF NOT EXISTS scheduler_state_seq;

-- Table: tracked_entity
-- Company/entity tracking with per-entity alert config
CREATE TABLE IF NOT EXISTS tracked_entity (
    entity_id BIGINT PRIMARY KEY DEFAULT nextval('tracked_entity_seq'),
    symbol VARCHAR NOT NULL,
    isin VARCHAR,
    company_name VARCHAR,
    entity_type VARCHAR NOT NULL DEFAULT 'stock',
    sector VARCHAR,
    market_cap_cr DOUBLE,
    source_list VARCHAR,
    priority INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    aliases_json VARCHAR,
    alert_config_json VARCHAR,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE(symbol)
);

-- Table: raw_event
-- Raw fetched events from RSS/API
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

-- Table: resolved_event
-- Analyzed events with insights
CREATE TABLE IF NOT EXISTS resolved_event (
    resolved_event_id BIGINT PRIMARY KEY DEFAULT nextval('resolved_event_seq'),
    raw_event_id BIGINT NOT NULL,
    insight_id BIGINT,
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
    one_line_summary VARCHAR,
    financials_json VARCHAR,
    risk_flags_json VARCHAR,
    period_label VARCHAR,
    key_facts_json VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'pending',
    resolved_at TIMESTAMP,
    acknowledged_at TIMESTAMP,
    event_tier VARCHAR,
    ignored_reason VARCHAR,
    UNIQUE(raw_event_id)
);

-- Table: filing_document
-- PDF attachments with extraction status
CREATE TABLE IF NOT EXISTS filing_document (
    document_id BIGINT PRIMARY KEY DEFAULT nextval('filing_document_seq'),
    raw_event_id BIGINT NOT NULL,
    source_url VARCHAR NOT NULL,
    local_path VARCHAR,
    content_hash VARCHAR,
    mime_type VARCHAR,
    file_size BIGINT DEFAULT 0,
    pdf_status VARCHAR NOT NULL DEFAULT 'pending',
    extraction_method VARCHAR,
    extracted_text VARCHAR,
    llm_insight_json VARCHAR,
    download_attempts INTEGER NOT NULL DEFAULT 0,
    downloaded_at TIMESTAMP,
    extracted_at TIMESTAMP,
    error_message VARCHAR,
    UNIQUE(source_url)
);

-- Table: llm_insight
-- LLM-generated insights (decoupled for reprocessing)
CREATE TABLE IF NOT EXISTS llm_insight (
    insight_id BIGINT PRIMARY KEY DEFAULT nextval('llm_insight_seq'),
    raw_event_id BIGINT NOT NULL,
    document_id BIGINT,
    model_used VARCHAR NOT NULL,
    provider VARCHAR NOT NULL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    insight_json VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

-- Table: alert_log
-- Alert delivery tracking
CREATE TABLE IF NOT EXISTS alert_log (
    alert_id BIGINT PRIMARY KEY DEFAULT nextval('alert_log_seq'),
    resolved_event_id BIGINT NOT NULL,
    channel VARCHAR NOT NULL,
    alert_status VARCHAR NOT NULL,
    priority VARCHAR NOT NULL DEFAULT 'normal',
    sent_at TIMESTAMP,
    acknowledged_at TIMESTAMP,
    payload_json VARCHAR,
    error_message VARCHAR,
    UNIQUE(resolved_event_id, channel)
);

-- Table: scheduler_state
-- Scheduler health tracking
CREATE TABLE IF NOT EXISTS scheduler_state (
    state_id BIGINT PRIMARY KEY DEFAULT nextval('scheduler_state_seq'),
    last_heartbeat TIMESTAMP,
    last_cycle_at TIMESTAMP,
    cycle_stats_json VARCHAR,
    error_count INTEGER DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

-- ---------------------------------------------------------------------------
-- v2.1 additions: bulk/block deals, insider trades, credit-rating changes,
-- SAST filings. These power the trading-system enrichment use case.
-- ---------------------------------------------------------------------------

CREATE SEQUENCE IF NOT EXISTS bulk_deal_seq;
CREATE SEQUENCE IF NOT EXISTS insider_trade_seq;
CREATE SEQUENCE IF NOT EXISTS rating_change_seq;
CREATE SEQUENCE IF NOT EXISTS sast_filing_seq;

-- Table: bulk_deal
-- NSE/BSE bulk + block deals (institutional transactions ≥ 0.5% of equity)
CREATE TABLE IF NOT EXISTS bulk_deal (
    bulk_deal_id BIGINT PRIMARY KEY DEFAULT nextval('bulk_deal_seq'),
    trade_date DATE NOT NULL,
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    client_name VARCHAR,
    side VARCHAR NOT NULL,
    quantity BIGINT,
    avg_price DOUBLE,
    deal_value_cr DOUBLE,
    is_block BOOLEAN NOT NULL DEFAULT FALSE,
    source_url VARCHAR,
    deal_hash VARCHAR NOT NULL,
    ingested_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE(deal_hash)
);

-- Table: insider_trade
-- PIT Reg 7(2) insider transaction disclosures (NSE/BSE)
CREATE TABLE IF NOT EXISTS insider_trade (
    insider_trade_id BIGINT PRIMARY KEY DEFAULT nextval('insider_trade_seq'),
    symbol VARCHAR NOT NULL,
    person_name VARCHAR,
    designation VARCHAR,
    relation_to_company VARCHAR,
    txn_type VARCHAR,
    quantity BIGINT,
    value_cr DOUBLE,
    txn_date DATE,
    disclosed_date DATE,
    holding_pre_pct DOUBLE,
    holding_post_pct DOUBLE,
    source_url VARCHAR,
    txn_hash VARCHAR NOT NULL,
    ingested_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE(txn_hash)
);

-- Table: rating_change
-- Credit-rating actions from CRISIL/ICRA/CARE/India Ratings
CREATE TABLE IF NOT EXISTS rating_change (
    rating_change_id BIGINT PRIMARY KEY DEFAULT nextval('rating_change_seq'),
    symbol VARCHAR,
    company_name VARCHAR,
    agency VARCHAR NOT NULL,
    instrument VARCHAR,
    old_rating VARCHAR,
    new_rating VARCHAR,
    action VARCHAR,
    rationale_excerpt VARCHAR,
    dated DATE,
    source_url VARCHAR,
    change_hash VARCHAR NOT NULL,
    ingested_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE(change_hash)
);

-- Table: sast_filing
-- Substantial Acquisition of Shares & Takeovers (SEBI Reg 29 disclosures)
CREATE TABLE IF NOT EXISTS sast_filing (
    sast_filing_id BIGINT PRIMARY KEY DEFAULT nextval('sast_filing_seq'),
    symbol VARCHAR NOT NULL,
    acquirer_name VARCHAR,
    regulation VARCHAR,
    txn_type VARCHAR,
    pre_acquisition_pct DOUBLE,
    post_acquisition_pct DOUBLE,
    quantity BIGINT,
    value_cr DOUBLE,
    txn_date DATE,
    disclosed_date DATE,
    source_url VARCHAR,
    filing_hash VARCHAR NOT NULL,
    ingested_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE(filing_hash)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tracked_entity_active ON tracked_entity(is_active);
CREATE INDEX IF NOT EXISTS idx_tracked_entity_symbol ON tracked_entity(symbol);
CREATE INDEX IF NOT EXISTS idx_raw_event_symbol ON raw_event(symbol);
CREATE INDEX IF NOT EXISTS idx_raw_event_event_date ON raw_event(event_date);
CREATE INDEX IF NOT EXISTS idx_raw_event_status ON raw_event(processing_status);
CREATE INDEX IF NOT EXISTS idx_raw_event_hash_seen ON raw_event(event_hash, seen_count);
CREATE INDEX IF NOT EXISTS idx_resolved_event_entity_id ON resolved_event(entity_id);
CREATE INDEX IF NOT EXISTS idx_resolved_event_alert_level ON resolved_event(alert_level);
CREATE INDEX IF NOT EXISTS idx_resolved_event_status ON resolved_event(status);
CREATE INDEX IF NOT EXISTS idx_resolved_event_insight ON resolved_event(insight_id);
CREATE INDEX IF NOT EXISTS idx_filing_document_raw_event_id ON filing_document(raw_event_id);
CREATE INDEX IF NOT EXISTS idx_filing_document_status ON filing_document(pdf_status);
CREATE INDEX IF NOT EXISTS idx_llm_insight_raw_event ON llm_insight(raw_event_id);
CREATE INDEX IF NOT EXISTS idx_alert_log_event_id ON alert_log(resolved_event_id);
CREATE INDEX IF NOT EXISTS idx_scheduler_heartbeat ON scheduler_state(last_heartbeat);
CREATE INDEX IF NOT EXISTS idx_bulk_deal_symbol_date ON bulk_deal(symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_bulk_deal_trade_date ON bulk_deal(trade_date);
CREATE INDEX IF NOT EXISTS idx_insider_trade_symbol_date ON insider_trade(symbol, txn_date);
CREATE INDEX IF NOT EXISTS idx_insider_trade_disclosed ON insider_trade(disclosed_date);
CREATE INDEX IF NOT EXISTS idx_rating_change_symbol_dated ON rating_change(symbol, dated);
CREATE INDEX IF NOT EXISTS idx_sast_filing_symbol_date ON sast_filing(symbol, txn_date);