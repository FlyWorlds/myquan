package com.myquan.backend.holdings;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import static org.junit.jupiter.api.Assertions.*;

class HoldingsServiceTest {
    @TempDir Path directory;
    private Path file;
    private HoldingsService service;
    private JdbcTemplate jdbc;

    @BeforeEach
    void setup() {
        file = directory.resolve("holdings.json");
        var dataSource = new DriverManagerDataSource("jdbc:h2:mem:" + directory.getFileName() + ";MODE=MySQL;DB_CLOSE_DELAY=-1", "sa", "");
        jdbc = new JdbcTemplate(dataSource);
        jdbc.execute("CREATE TABLE paper_holdings_sync (id INT PRIMARY KEY, source_updated_at TIMESTAMP, source_digest CHAR(64), synced_at TIMESTAMP)");
        jdbc.execute("INSERT INTO paper_holdings_sync (id) VALUES (1)");
        jdbc.execute("CREATE TABLE paper_holdings (code CHAR(6) PRIMARY KEY, name VARCHAR(128), market VARCHAR(32), qty BIGINT, available BIGINT, cost DECIMAL(20,8), buy_time VARCHAR(32), peak_high DECIMAL(20,8), note TEXT)");
        service = new HoldingsService(jdbc, new TransactionTemplate(new DataSourceTransactionManager(dataSource)), new ObjectMapper(), file.toString());
    }

    private void write(String time, String positions) throws Exception {
        Files.writeString(file, "{\"updated_at\":\"" + time + "\",\"positions\":" + positions + "}");
    }

    @Test
    void importsOnlyActualHoldingsWithExactCostsAndIsIdempotent() throws Exception {
        write("2026-10-14 19:42:13", "{\"002841\":{\"qty\":1300,\"available\":0,\"cost\":43.65},\"600072\":{\"qty\":6000,\"cost\":9.76},\"000001\":{\"qty\":0}}");
        assertEquals(2, service.sync().get("count"));
        assertEquals(false, service.sync().get("changed"));
        assertEquals("43.65000000", jdbc.queryForObject("SELECT cost FROM paper_holdings WHERE code='002841'", java.math.BigDecimal.class).toPlainString());
        assertNull(jdbc.queryForMap("SELECT * FROM paper_holdings WHERE code='600072'").get("AVAILABLE"));
        assertEquals(2, service.snapshot().get("count"));
    }

    @Test
    void removesClosedPositionsAndAcceptsValidEmptySnapshot() throws Exception {
        write("2026-10-14 19:42:13", "{\"002841\":{\"qty\":1300,\"cost\":43.65}}");
        service.sync();
        write("2026-10-14 19:42:14", "{}");
        assertEquals(0, service.sync().get("count"));
        assertEquals(0, service.snapshot().get("count"));
    }

    @Test
    void invalidSourceCannotEraseSnapshot() throws Exception {
        write("2026-10-14 19:42:13", "{\"002841\":{\"qty\":1300,\"cost\":43.65}}");
        service.sync();
        for (var invalid : new String[]{"{}", "{\"updated_at\":\"2026-10-14 19:42:14\",\"positions\":{\"002841\":{\"qty\":-1}}}", "not-json"}) {
            Files.writeString(file, invalid);
            assertThrows(ResponseStatusException.class, service::sync);
            assertEquals(1, service.snapshot().get("count"));
        }
        Files.delete(file);
        assertThrows(ResponseStatusException.class, service::sync);
        assertEquals(1, service.snapshot().get("count"));
    }

    @Test
    void rejectsOlderSnapshot() throws Exception {
        write("2026-10-14 19:42:13", "{\"002841\":{\"qty\":1300,\"cost\":43.65}}");
        service.sync();
        write("2026-10-13 19:42:13", "{}");
        assertEquals(409, assertThrows(ResponseStatusException.class, service::sync).getStatusCode().value());
        assertEquals(1, service.snapshot().get("count"));
    }
}
