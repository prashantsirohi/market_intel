CREATE SEQUENCE IF NOT EXISTS bulk_deal_seq;
CREATE SEQUENCE IF NOT EXISTS insider_trade_seq;
CREATE SEQUENCE IF NOT EXISTS rating_change_seq;
CREATE SEQUENCE IF NOT EXISTS sast_filing_seq;

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

CREATE INDEX IF NOT EXISTS idx_bulk_deal_symbol_date ON bulk_deal(symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_bulk_deal_trade_date ON bulk_deal(trade_date);
CREATE INDEX IF NOT EXISTS idx_insider_trade_symbol_date ON insider_trade(symbol, txn_date);
CREATE INDEX IF NOT EXISTS idx_insider_trade_disclosed ON insider_trade(disclosed_date);
CREATE INDEX IF NOT EXISTS idx_rating_change_symbol_dated ON rating_change(symbol, dated);
CREATE INDEX IF NOT EXISTS idx_sast_filing_symbol_date ON sast_filing(symbol, txn_date);
