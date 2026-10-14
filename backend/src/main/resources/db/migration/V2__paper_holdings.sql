CREATE TABLE paper_holdings_sync (
    id INT NOT NULL PRIMARY KEY,
    source_updated_at DATETIME NULL,
    source_digest CHAR(64) NULL,
    synced_at DATETIME(6) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT INTO paper_holdings_sync (id) VALUES (1);

CREATE TABLE paper_holdings (
    code CHAR(6) NOT NULL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    market VARCHAR(32) NOT NULL,
    qty BIGINT NOT NULL,
    available BIGINT NULL,
    cost DECIMAL(20,8) NOT NULL,
    buy_time VARCHAR(32) NULL,
    peak_high DECIMAL(20,8) NULL,
    note TEXT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
UPDATE backend_metadata SET meta_value = '2' WHERE meta_key = 'schema_version';
