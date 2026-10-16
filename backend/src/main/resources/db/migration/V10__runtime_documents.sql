CREATE TABLE app_documents (
    doc_key VARCHAR(64) NOT NULL PRIMARY KEY,
    revision BIGINT NOT NULL,
    payload LONGTEXT NOT NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE app_document_writes (
    request_id VARCHAR(64) NOT NULL PRIMARY KEY,
    doc_key VARCHAR(64) NOT NULL,
    payload_hash CHAR(64) NOT NULL,
    revision BIGINT NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE strategy_sim_voided_events (
    event_id VARCHAR(64) NOT NULL PRIMARY KEY,
    strategy_id VARCHAR(32) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    side VARCHAR(8) NOT NULL,
    session_date CHAR(10) NULL,
    payload LONGTEXT NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

UPDATE backend_metadata SET meta_value='10' WHERE meta_key='schema_version';
