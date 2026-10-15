ALTER TABLE strategy_symbol_events
    ADD COLUMN book_revision BIGINT NOT NULL DEFAULT 0;
ALTER TABLE strategy_symbol_events ADD COLUMN cost_price DECIMAL(20,8) NULL;
ALTER TABLE strategy_symbol_events ADD COLUMN realized_pnl DECIMAL(20,2) NULL;
ALTER TABLE strategy_symbol_events ADD COLUMN after_qty BIGINT NULL;
ALTER TABLE strategy_symbol_events ADD COLUMN cash_after DECIMAL(20,8) NULL;
CREATE INDEX idx_strategy_event_revision ON strategy_symbol_events(strategy_id,symbol,book_revision);
UPDATE backend_metadata SET meta_value='6' WHERE meta_key='schema_version';
