CREATE TABLE paper_account_snapshots (
    snapshot_key VARCHAR(64) NOT NULL PRIMARY KEY,
    trading_day DATE NOT NULL,
    observed_at DATETIME NOT NULL,
    account_revision BIGINT NOT NULL,
    total_pnl DECIMAL(20,2) NULL,
    total_pnl_pct DECIMAL(12,6) NULL,
    day_pnl DECIMAL(20,2) NULL,
    day_pnl_pct DECIMAL(12,6) NULL,
    position_pct DECIMAL(12,6) NULL,
    account_total DECIMAL(20,2) NULL,
    account_cash DECIMAL(20,2) NULL,
    market_value DECIMAL(20,2) NULL,
    account_payload LONGTEXT NOT NULL,
    holdings_payload LONGTEXT NOT NULL,
    closed_payload LONGTEXT NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_account_snapshots_day (trading_day, observed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE VIEW paper_closed_trades AS
SELECT sequence_no, entry_id, code, executed_at,
    NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload,'$.name')),'null') AS name,
    CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload,'$.qty')),'null') AS SIGNED) AS last_fill_qty,
    CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload,'$.price')),'null') AS DECIMAL(20,8)) AS last_fill_price,
    CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload,'$.cost')),'null') AS DECIMAL(20,8)) AS cost,
    CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload,'$.pnl')),'null') AS DECIMAL(20,2)) AS last_fill_pnl,
    CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload,'$.pnl_pct')),'null') AS DECIMAL(12,6)) AS last_fill_pnl_pct,
    NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload,'$.buy_time')),'null') AS buy_time,
    NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload,'$.reason')),'null') AS reason
FROM paper_delivery_entries
WHERE side='sell' AND CAST(JSON_UNQUOTE(JSON_EXTRACT(payload,'$.after_qty')) AS SIGNED)=0;

UPDATE backend_metadata SET meta_value='4' WHERE meta_key='schema_version';
