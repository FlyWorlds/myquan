CREATE TABLE market_quote_latest (
    symbol VARCHAR(16) PRIMARY KEY,
    revision BIGINT NOT NULL DEFAULT 0,
    source_at VARCHAR(32) NOT NULL,
    received_at VARCHAR(32) NOT NULL,
    payload_hash CHAR(64) NOT NULL,
    payload LONGTEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
