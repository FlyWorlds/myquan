package com.myquan.backend.holdings;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import static org.junit.jupiter.api.Assertions.*;

class DocumentServiceTest {
    private final ObjectMapper mapper = new ObjectMapper();
    private DocumentService documents;
    private StrategySimVoidService voids;

    @BeforeEach void setup() throws Exception {
        var ds = new DriverManagerDataSource("jdbc:h2:mem:" + UUID.randomUUID() + ";MODE=MySQL;DB_CLOSE_DELAY=-1", "sa", "");
        var jdbc = new JdbcTemplate(ds);
        jdbc.execute("CREATE TABLE backend_metadata (meta_key VARCHAR(64) PRIMARY KEY, meta_value VARCHAR(255) NOT NULL)");
        jdbc.update("INSERT INTO backend_metadata (meta_key, meta_value) VALUES ('schema_version', '9')");
        new ResourceDatabasePopulator(new ClassPathResource("db/migration/V10__runtime_documents.sql")).execute(ds);
        var tx = new TransactionTemplate(new DataSourceTransactionManager(ds));
        documents = new DocumentService(jdbc, tx, mapper);
        voids = new StrategySimVoidService(jdbc, tx, mapper);
    }

    @Test void missingDocumentStartsAtRevisionZeroAndRejectsStaleWrites() throws Exception {
        assertEquals(0, documents.read("watch_snapshot").revision());
        var payload = mapper.readTree("{\"type\":\"snapshot\"}");
        var saved = documents.write("watch_snapshot", new DocumentService.Write(0L, "req-1", payload));
        assertEquals(1, saved.revision());
        assertThrows(ResponseStatusException.class, () ->
                documents.write("watch_snapshot", new DocumentService.Write(0L, "req-2", payload)));
        var again = documents.write("watch_snapshot", new DocumentService.Write(1L, "req-1", payload));
        assertEquals(1, again.revision());
    }

    @Test void voidedEventsInsertOnce() throws Exception {
        var body = mapper.readTree("""
                {"events":[{"event_id":"94aa8892-89ec-51ae-9045-312eb9f1808c","strategy_id":"strategy16","symbol":"600330","side":"BUY","trading_session_date":"2026-10-15"}]}
                """);
        assertEquals(1, ((Number) voids.append(body).get("inserted")).intValue());
        assertEquals(0, ((Number) voids.append(body).get("inserted")).intValue());
        assertEquals(1L, voids.count().get("count"));
    }
}
