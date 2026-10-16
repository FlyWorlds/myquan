CREATE TABLE strategy_selection_preferences (
 id INT PRIMARY KEY,
 default_group_id VARCHAR(36) NULL,
 FOREIGN KEY (default_group_id) REFERENCES strategy_selection_groups(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT INTO strategy_selection_preferences(id,default_group_id) VALUES(1,NULL);
UPDATE backend_metadata SET meta_value='9' WHERE meta_key='schema_version';
