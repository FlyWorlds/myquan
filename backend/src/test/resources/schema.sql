CREATE TABLE backend_metadata (
    meta_key VARCHAR(64) PRIMARY KEY,
    meta_value VARCHAR(255) NOT NULL
);
INSERT INTO backend_metadata (meta_key, meta_value) VALUES ('schema_version', '1');

