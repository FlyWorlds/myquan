package com.myquan.backend.holdings;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import static org.junit.jupiter.api.Assertions.*;

class PaperStateServiceTest {
    private final ObjectMapper mapper = new ObjectMapper().enable(com.fasterxml.jackson.databind.DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS);
    private JdbcTemplate jdbc;
    private PaperStateService service;

    @BeforeEach
    void setup() {
        var ds = new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1", "sa", "");
        jdbc = new JdbcTemplate(ds);
        var tx = new TransactionTemplate(new DataSourceTransactionManager(ds));
        jdbc.execute("CREATE TABLE paper_account_state (id INT PRIMARY KEY,revision BIGINT,holdings CLOB,trades CLOB,ledger CLOB,updated_at TIMESTAMP)");
        jdbc.execute("INSERT INTO paper_account_state (id,revision) VALUES (1,0)");
        jdbc.execute("CREATE TABLE paper_state_writes (request_id VARCHAR(64) PRIMARY KEY,payload_hash CHAR(64),revision BIGINT)");
        jdbc.execute("CREATE TABLE paper_holdings_sync (id INT PRIMARY KEY,source_updated_at TIMESTAMP,source_digest CHAR(64),synced_at TIMESTAMP)");
        jdbc.execute("INSERT INTO paper_holdings_sync (id) VALUES (1)");
        jdbc.execute("CREATE TABLE paper_holdings (code CHAR(6) PRIMARY KEY,name VARCHAR(128),market VARCHAR(32),qty BIGINT,available BIGINT,cost DECIMAL(20,8),buy_time VARCHAR(32),peak_high DECIMAL(20,8),note TEXT)");
        jdbc.execute("CREATE TABLE paper_trade_history (sequence_no BIGINT PRIMARY KEY,code VARCHAR(16),side VARCHAR(32),executed_at VARCHAR(32),payload CLOB)");
        jdbc.execute("CREATE TABLE paper_delivery_entries (sequence_no BIGINT PRIMARY KEY,entry_id VARCHAR(64),code VARCHAR(16),side VARCHAR(32),executed_at VARCHAR(32),payload CLOB)");
        service = new PaperStateService(jdbc, tx, mapper, new HoldingsService(jdbc,tx,mapper,"missing.json"),"missing.json");
    }

    private PaperStateService.Write write(long version, String id, String holdings) throws Exception {
        return new PaperStateService.Write(version,id,mapper.readTree(holdings),mapper.readTree("[]"),mapper.readTree("{\"entries\":[]}"));
    }

    @Test
    void preservesCompleteStateAndMaterializesPositiveHoldings() throws Exception {
        var input = write(0,"first","{\"positions\":{\"002841\":{\"qty\":1300,\"cost\":43.65},\"000001\":{\"qty\":0}},\"account_cash\":179535,\"slot_queue\":{\"extra\":7}}");
        assertEquals(1,service.write(input).revision());
        assertEquals(input.holdings(), service.read().holdings());
        assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM paper_holdings",Integer.class));
    }

    @Test
    void repeatedRequestCommitsOnlyOnceAndRejectsStaleWriter() throws Exception {
        var input = write(0,"same","{\"positions\":{}}");
        assertEquals(1,service.write(input).revision());
        assertEquals(1,service.write(input).revision());
        assertThrows(ResponseStatusException.class, () -> service.write(write(0,"other","{\"positions\":{}}")));
        assertThrows(ResponseStatusException.class, () -> service.write(write(1,"same","{\"positions\":{},\"account_cash\":3}")));
        assertEquals(1,service.read().revision());
    }

    @Test
    void cashHoldingsAndTradeHistoryCommitTogether() throws Exception {
        var input=write(0,"buy","{\"positions\":{\"002841\":{\"qty\":100,\"available\":0,\"cost\":43.65}},\"account_cash\":95635}");
        var trade=mapper.readTree("{\"code\":\"002841\",\"side\":\"buy\",\"time\":\"2026-10-14 10:31:00\",\"qty\":100}");
        var trades=mapper.createArrayNode().add(trade);
        var ledger=mapper.createObjectNode().set("entries",mapper.createArrayNode().add(trade));
        service.write(new PaperStateService.Write(0L,"buy",input.holdings(),trades,ledger));
        assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM paper_delivery_entries",Integer.class));
        assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM paper_trade_history",Integer.class));
        assertEquals(95635,service.read().holdings().get("account_cash").asInt());
    }

    @Test
    void failureRollsBackAllTables() throws Exception {
        service.write(write(0,"initial","{\"positions\":{},\"account_cash\":100000}"));
        var input=write(1,"bad","{\"positions\":{\"002841\":{\"qty\":100,\"cost\":43.65}},\"account_cash\":95635}");
        var badTrade=mapper.createArrayNode().add(mapper.createObjectNode().put("code","x".repeat(100)));
        assertThrows(org.springframework.dao.DataAccessException.class, () -> service.write(new PaperStateService.Write(1L,"bad",input.holdings(),badTrade,input.ledger())));
        assertEquals(1,service.read().revision());
        assertEquals(100000,service.read().holdings().get("account_cash").asInt());
        assertEquals(0,jdbc.queryForObject("SELECT COUNT(*) FROM paper_holdings",Integer.class));
    }

    @Test
    void invalidPositionAndRepeatedMigrationCannotOverwriteState() throws Exception {
        service.write(write(0,"initial","{\"positions\":{}}"));
        assertThrows(ResponseStatusException.class,service::migrate);
        assertThrows(ResponseStatusException.class, () -> service.write(write(1,"negative","{\"positions\":{\"002841\":{\"qty\":-1}}}")));
        assertEquals(1,service.read().revision());
    }

    @Test
    void committedHistoryCannotBeTruncatedOrRewritten() throws Exception {
        var input=write(0,"initial","{\"positions\":{}}");
        var trade=mapper.readTree("{\"side\":\"buy\",\"qty\":100}");
        var history=mapper.createArrayNode().add(trade);
        var ledger=mapper.createObjectNode().set("entries",mapper.createArrayNode().add(trade));
        service.write(new PaperStateService.Write(0L,"initial",input.holdings(),history,ledger));
        assertThrows(ResponseStatusException.class, () -> service.write(write(1,"delete","{\"positions\":{}}")));
        var altered=mapper.createArrayNode().add(mapper.createObjectNode().put("side","buy").put("qty",200));
        assertThrows(ResponseStatusException.class, () -> service.write(new PaperStateService.Write(1L,"alter",input.holdings(),altered,ledger)));
        var archived=history.deepCopy();
        ((com.fasterxml.jackson.databind.node.ObjectNode)archived.get(0)).put("reset_archived",true);
        service.write(new PaperStateService.Write(1L,"archive",input.holdings(),archived,ledger));
        assertThrows(ResponseStatusException.class, () -> service.write(new PaperStateService.Write(2L,"unarchive",input.holdings(),history,ledger)));
        assertTrue(service.read().trades().get(0).path("reset_archived").asBoolean());
    }

    @Test
    void missingRevisionIsRejected() throws Exception {
        var input=write(0,"initial","{\"positions\":{}}");
        assertThrows(ResponseStatusException.class, () -> service.write(new PaperStateService.Write(null,"missing",input.holdings(),input.trades(),input.ledger())));
    }

    @Test
    void concurrentWritersCannotCommitTheSameRevisionTwice() throws Exception {
        var first=write(0,"writer1","{\"positions\":{},\"account_cash\":100}");
        var second=write(0,"writer2","{\"positions\":{},\"account_cash\":200}");
        var gate=new java.util.concurrent.CountDownLatch(1);
        try (var executor=java.util.concurrent.Executors.newFixedThreadPool(2)) {
            var a=executor.submit(() -> { gate.await(); try { service.write(first); return true; }
                catch (ResponseStatusException exception) { return false; } });
            var b=executor.submit(() -> { gate.await(); try { service.write(second); return true; }
                catch (ResponseStatusException exception) { return false; } });
            gate.countDown();
            assertNotEquals(a.get(),b.get());
        }
        assertEquals(1,service.read().revision());
        assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM paper_state_writes",Integer.class));
    }

    @Test
    void equivalentNumericFormattingDoesNotLookLikeAHistoryRewrite() throws Exception {
        var input=write(0,"initial","{\"positions\":{}}");
        var first=mapper.readTree("[{\"side\":\"buy\",\"price\":10.0}]");
        var second=mapper.readTree("[{\"side\":\"buy\",\"price\":10}]");
        service.write(new PaperStateService.Write(0L,"initial",input.holdings(),first,input.ledger()));
        assertEquals(2,service.write(new PaperStateService.Write(1L,"same-value",input.holdings(),second,input.ledger())).revision());
    }

    @Test
    void partialAccountDocumentCannotEraseCashAndRuntimeState() throws Exception {
        service.write(write(0,"initial","{\"positions\":{},\"account_cash\":100,\"slot_queue\":{}}"));
        assertThrows(ResponseStatusException.class, () -> service.write(write(1,"partial","{\"positions\":{}}")));
        assertEquals(100,service.read().holdings().get("account_cash").asInt());
    }
}
