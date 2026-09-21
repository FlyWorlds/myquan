-- Paper Trading Remote State — Phase R1 schema
-- Backend: PostgreSQL
-- Secrets: PAPER_DATABASE_URL only (never commit credentials)
-- Timestamps: store UTC; trading_session_date is A-share calendar date (Asia/Shanghai semantics)

BEGIN;

CREATE TABLE IF NOT EXISTS paper_accounts (
    account_id              TEXT PRIMARY KEY,
    paper_equity_base       DOUBLE PRECISION,
    account_cash            DOUBLE PRECISION,
    account_total           DOUBLE PRECISION,
    account_total_open      DOUBLE PRECISION,
    account_total_open_session CHAR(10),
    trading_session_date    CHAR(10),
    last_session            CHAR(10),
    paper_pnl_start         CHAR(10),
    version                 BIGINT NOT NULL DEFAULT 0,
    extra                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS paper_positions (
    account_id              TEXT NOT NULL REFERENCES paper_accounts(account_id),
    symbol                  CHAR(6) NOT NULL,
    qty                     INTEGER NOT NULL DEFAULT 0,
    available               INTEGER,
    cost                    DOUBLE PRECISION,
    today_cost              DOUBLE PRECISION,
    buy_time                TEXT,
    name                    TEXT,
    market                  TEXT,
    note                    TEXT,
    peak_high               DOUBLE PRECISION,
    overnight_peak          DOUBLE PRECISION,
    overnight_peak_session  CHAR(10),
    stop_noted              BOOLEAN NOT NULL DEFAULT FALSE,
    stop_noted_px           DOUBLE PRECISION,
    stop_noted_session      CHAR(10),
    tp_stage                INTEGER NOT NULL DEFAULT 0,
    last_tp_ts              TEXT,
    version                 BIGINT NOT NULL DEFAULT 0,
    extra                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_paper_positions_open
    ON paper_positions (account_id) WHERE qty > 0;

-- Append-only trades; execution_id unique for idempotent retries
CREATE TABLE IF NOT EXISTS paper_trades (
    trade_id                TEXT PRIMARY KEY,
    account_id              TEXT NOT NULL REFERENCES paper_accounts(account_id),
    execution_id            TEXT NOT NULL,
    symbol                  CHAR(6) NOT NULL,
    side                    TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    qty                     INTEGER NOT NULL,
    fill_price              DOUBLE PRECISION NOT NULL,
    cost_basis              DOUBLE PRECISION,
    realized_pnl            DOUBLE PRECISION,
    reason_code             TEXT,
    strategy_id             TEXT,
    note                    TEXT,
    after_qty               INTEGER,
    trading_session_date    CHAR(10) NOT NULL,
    executed_at             TIMESTAMPTZ NOT NULL,
    payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (account_id, execution_id)
);

CREATE INDEX IF NOT EXISTS idx_paper_trades_session
    ON paper_trades (account_id, trading_session_date);

CREATE TABLE IF NOT EXISTS paper_daily_state (
    account_id              TEXT NOT NULL REFERENCES paper_accounts(account_id),
    trading_session_date    CHAR(10) NOT NULL,
    opening_equity          DOUBLE PRECISION,
    closing_equity          DOUBLE PRECISION,
    settled                 BOOLEAN NOT NULL DEFAULT FALSE,
    settled_at              TIMESTAMPTZ,
    payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (account_id, trading_session_date)
);

-- Runtime bags that affect cross-machine correctness but aren't row-normalized yet
CREATE TABLE IF NOT EXISTS paper_runtime_state (
    account_id              TEXT NOT NULL REFERENCES paper_accounts(account_id),
    key                     TEXT NOT NULL,
    value                   JSONB NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account_id, key)
);
-- keys: realized_today, closed_today, slot_queue, factor_memory, factor2, portfolio_pool, alert_sticky

CREATE TABLE IF NOT EXISTS paper_writer_lease (
    account_id              TEXT PRIMARY KEY REFERENCES paper_accounts(account_id),
    writer_id               TEXT NOT NULL,
    hostname                TEXT NOT NULL,
    lease_token             TEXT NOT NULL,
    fencing_token           BIGINT NOT NULL,
    lease_expires_at        TIMESTAMPTZ NOT NULL,
    heartbeat_at            TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
