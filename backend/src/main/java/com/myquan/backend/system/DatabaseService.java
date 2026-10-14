package com.myquan.backend.system;

import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class DatabaseService {
    private final JdbcTemplate jdbcTemplate;

    public DatabaseService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public DatabaseStatus status() {
        return jdbcTemplate.execute((ConnectionCallback<DatabaseStatus>) connection -> {
            var metadata = connection.getMetaData();
            try (var statement = connection.prepareStatement(
                    "SELECT meta_value FROM backend_metadata WHERE meta_key = ?")) {
                statement.setString(1, "schema_version");
                try (var result = statement.executeQuery()) {
                    if (!result.next()) {
                        throw new java.sql.SQLException("Backend schema version is missing");
                    }
                    return new DatabaseStatus(connection.getCatalog(), metadata.getDatabaseProductName(),
                            metadata.getDatabaseProductVersion(), result.getString(1));
                }
            }
        });
    }
}

