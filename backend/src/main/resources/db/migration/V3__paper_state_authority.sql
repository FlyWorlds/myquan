CREATE TABLE paper_account_state (
    id INT NOT NULL PRIMARY KEY,
    revision BIGINT NOT NULL DEFAULT 0,
    holdings LONGTEXT NULL,
    trades LONGTEXT NULL,
    ledger LONGTEXT NULL,
    updated_at DATETIME(6) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT INTO paper_account_state (id) VALUES (1);

CREATE TABLE paper_state_writes (
    request_id VARCHAR(64) NOT NULL PRIMARY KEY,
    payload_hash CHAR(64) NOT NULL,
    revision BIGINT NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE paper_trade_history (
    sequence_no BIGINT NOT NULL PRIMARY KEY,
    code VARCHAR(16) NOT NULL,
    side VARCHAR(32) NOT NULL,
    executed_at VARCHAR(32) NOT NULL,
    payload LONGTEXT NOT NULL,
    INDEX idx_paper_trade_symbol (code, executed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE paper_delivery_entries (
    sequence_no BIGINT NOT NULL PRIMARY KEY,
    entry_id VARCHAR(64) NOT NULL,
    code VARCHAR(16) NOT NULL,
    side VARCHAR(32) NOT NULL,
    executed_at VARCHAR(32) NOT NULL,
    payload LONGTEXT NOT NULL,
    INDEX idx_paper_delivery_symbol (code, executed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
UPDATE backend_metadata SET meta_value='3' WHERE meta_key='schema_version';
