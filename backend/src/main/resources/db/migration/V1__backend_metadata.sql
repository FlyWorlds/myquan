CREATE TABLE backend_metadata (
    meta_key VARCHAR(64) NOT NULL,
    meta_value VARCHAR(255) NOT NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (meta_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO backend_metadata (meta_key, meta_value)
VALUES ('schema_version', '1'), ('application', 'myquan-backend');

