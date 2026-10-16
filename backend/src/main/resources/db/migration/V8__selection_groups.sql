CREATE TABLE strategy_selection_groups (
 id VARCHAR(36) PRIMARY KEY,
 name VARCHAR(80) NOT NULL,
 payload LONGTEXT NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
UPDATE backend_metadata SET meta_value='8' WHERE meta_key='schema_version';
