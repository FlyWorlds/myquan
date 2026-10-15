CREATE TABLE strategy_symbol_books (
    strategy_id VARCHAR(32) NOT NULL,
    symbol CHAR(6) NOT NULL,
    revision BIGINT NOT NULL,
    qty BIGINT NOT NULL,
    entry_price DECIMAL(20,8) NULL,
    last_price DECIMAL(20,8) NULL,
    total_pnl DECIMAL(20,2) NULL,
    cycle_pnl DECIMAL(20,2) NULL,
    payload LONGTEXT NOT NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (strategy_id,symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE strategy_symbol_events (
    request_id VARCHAR(64) NOT NULL PRIMARY KEY,
    strategy_id VARCHAR(32) NOT NULL,
    symbol CHAR(6) NOT NULL,
    payload_hash CHAR(64) NOT NULL,
    side VARCHAR(8) NOT NULL,
    price DECIMAL(20,8) NULL,
    qty BIGINT NOT NULL,
    source_at VARCHAR(32) NOT NULL,
    decision_at VARCHAR(32) NOT NULL,
    payload LONGTEXT NOT NULL,
    INDEX idx_strategy_events (strategy_id,symbol,decision_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE strategy_legacy_checkpoints (
    strategy_id VARCHAR(32) NOT NULL,
    symbol CHAR(6) NOT NULL,
    source_hash CHAR(64) NOT NULL,
    payload LONGTEXT NOT NULL,
    imported_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (strategy_id,symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

UPDATE backend_metadata SET meta_value='5' WHERE meta_key='schema_version';
