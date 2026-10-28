package com.myquan.backend.holdings;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
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

class StrategyBookServiceTest {
    private final ObjectMapper mapper=new ObjectMapper();
    private JdbcTemplate jdbc;
    private StrategyBookService service;
    private final java.util.concurrent.atomic.AtomicReference<java.time.LocalDateTime> clock=
        new java.util.concurrent.atomic.AtomicReference<>(java.time.LocalDateTime.parse("2026-10-12T10:00:00"));
    @BeforeEach void setup() {
        var ds=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1","sa","");
        jdbc=new JdbcTemplate(ds);
        jdbc.execute("CREATE TABLE backend_metadata(meta_key VARCHAR(64),meta_value VARCHAR(64))");
        new ResourceDatabasePopulator(new ClassPathResource("db/migration/V5__strategy_symbol_books.sql"),
            new ClassPathResource("db/migration/V6__strategy_fill_accounting.sql")).execute(ds);
        service=new StrategyBookService(jdbc,new TransactionTemplate(new DataSourceTransactionManager(ds)),mapper,clock::get);
    }
    private StrategyBookService.Command fill(long revision, String id, String side, double price, long qty, double mark, String day) {
        String ts=day+" 10:00:00";
        clock.set(java.time.LocalDateTime.parse(ts.replace(' ','T')));
        return new StrategyBookService.Command(revision,id,side,BigDecimal.valueOf(price),qty,BigDecimal.valueOf(mark),ts,ts,null,"test");
    }
    private double amount(String key) { return service.books().get("000070").path(key).asDouble(); }
    @Test void strategiesHaveIndependentBooksAndEvents() {
        var s1=service.forStrategy("strategy1");
        s1.command("000070",fill(0,"strategy1-buy-0001","BUY",10,100,10,"2026-10-12"));
        assertTrue(service.books().isEmpty());
        assertEquals("strategy1",s1.books().get("000070").path("strategy_id").asText());
        service.command("000070",fill(0,"strategy16-buy-0001","BUY",11,200,11,"2026-10-12"));
        assertEquals(100,s1.books().get("000070").path("virtual_shares").asLong());
        assertEquals(200,service.books().get("000070").path("virtual_shares").asLong());
        assertEquals(1,s1.events("000070").size());
        assertEquals(1,service.events("000070").size());
    }
    @Test void requestIdCannotSilentlyReplayAcrossStrategies() {
        var buy=fill(0,"same-request-0001","BUY",10,100,10,"2026-10-12");
        service.command("000070",buy);
        var s1=service.forStrategy("strategy1");
        assertThrows(ResponseStatusException.class,()->s1.command("000070",buy));
        assertTrue(s1.books().isEmpty());
    }
    @Test void staleArrivalIsRejectedButCommittedRetryStillResolves() {
        var buy=fill(0,"fresh-live-buy","BUY",10,1000,10,"2026-10-12");
        clock.set(clock.get().plusSeconds(6));
        assertThrows(ResponseStatusException.class,()->service.command("000070",buy));
        assertTrue(service.books().isEmpty());
        clock.set(clock.get().minusSeconds(6));
        service.command("000070",buy);
        clock.set(clock.get().plusSeconds(10));
        service.command("000070",buy);
        assertEquals(1,service.events("000070").size());
    }
    @Test void partialSalesAndRepeatedCyclesUseProfitAmounts() {
        service.command("000070",fill(0,"buy-first","BUY",10,1000,10,"2026-10-12"));
        service.command("000070",fill(1,"sell-half","SELL",11,400,12,"2026-10-13"));
        assertEquals(1600,amount("total_pnl"));
        assertEquals(1.6,amount("cumulative_return_pct"));
        assertEquals(16,amount("cycle_return_pct"));
        assertEquals(20,amount("single_return_pct"));
        service.command("000070",fill(2,"sell-full","SELL",12,600,12,"2026-10-13"));
        service.command("000070",fill(3,"mark-flat","MARK",12,0,99,"2026-10-13"));
        assertEquals(1600,amount("total_pnl"));
        assertEquals(16,amount("cycle_return_pct"));
        service.command("000070",fill(4,"buy-second","BUY",20,1000,21,"2026-10-14"));
        assertEquals(2600,amount("total_pnl"));
        assertEquals(1000,amount("cycle_pnl"));
        assertEquals(5,amount("cycle_return_pct"));
        assertEquals(4,service.events("000070").size()); // MARK is not a fill event.
        var half=service.events("000070").get(1);
        assertEquals(400,((BigDecimal)half.get("REALIZED_PNL")).intValue());
        assertEquals(600,((Number)half.get("AFTER_QTY")).intValue());
    }
    @Test void duplicateRequestDoesNotTradeTwiceAndChangedPayloadIsRejected() {
        var buy=fill(0,"buy-first","BUY",10,1000,10,"2026-10-12");
        service.command("000070",buy);
        service.command("000070",buy);
        assertEquals(1,service.events("000070").size());
        assertThrows(ResponseStatusException.class,()->service.command("000070",fill(1,"buy-first","BUY",11,1000,11,"2026-10-12")));
        assertEquals(90000,amount("virtual_cash"));
    }
    @Test void jinAnMultipleSellLegsAreNotTheLastSalePercentage() {
        service.command("000070",fill(0,"cycle-buy","BUY",61.5,900,61.5,"2026-10-12"));
        service.command("000070",fill(1,"cycle-sell-a","SELL",67.65,400,67.65,"2026-10-13"));
        service.command("000070",fill(2,"cycle-sell-b","SELL",67.65,200,67.65,"2026-10-13"));
        service.command("000070",fill(3,"cycle-sell-c","SELL",70.72,300,70.72,"2026-10-13"));
        assertEquals(6456,amount("cycle_pnl"));
        assertEquals(11.663957,amount("cycle_return_pct"),.000001);
        assertEquals(106456,amount("virtual_cash"));
    }
    @Test void t1OversellAndStaleRevisionCannotChangeCash() {
        service.command("000070",fill(0,"buy-first","BUY",10,1000,10,"2026-10-12"));
        assertThrows(ResponseStatusException.class,()->service.command("000070",fill(1,"sell-today","SELL",11,100,11,"2026-10-12")));
        assertThrows(ResponseStatusException.class,()->service.command("000070",fill(1,"sell-excess","SELL",11,1100,11,"2026-10-13")));
        assertThrows(ResponseStatusException.class,()->service.command("000070",fill(0,"stale-sell","SELL",11,100,11,"2026-10-13")));
        assertEquals(90000,amount("virtual_cash"));
    }
    @Test void checkpointIsImmutableAndMarkedUnverified() throws Exception {
        var raw=mapper.readTree("{\"initial_cash\":100000,\"virtual_cash\":90000,\"virtual_shares\":1000,\"entry_price\":10,\"entry_time\":\"2026-10-12 10:00:00\",\"last_mark\":11,\"cumulative_return_pct\":999}");
        var result=service.checkpoint("000070",raw);
        assertEquals("legacy_checkpoint_unverified",result.path("history_status").asText());
        assertEquals(1,result.path("cumulative_return_pct").asDouble());
        var repeated=service.checkpoint("000070",raw);
        assertEquals(result.path("revision").asLong(),repeated.path("revision").asLong());
        assertEquals(0,result.path("total_pnl").decimalValue().compareTo(repeated.path("total_pnl").decimalValue()));
        assertThrows(ResponseStatusException.class,()->service.checkpoint("000070",mapper.readTree(raw.toString().replace("999","1"))));
        assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM strategy_legacy_checkpoints",Integer.class));
    }
    @Test void olderQuoteCannotRollBackMark() {
        service.command("000070",fill(0,"buy-first","BUY",10,1000,10,"2026-10-12"));
        service.command("000070",fill(1,"mark-later","MARK",10,0,12,"2026-10-14"));
        assertThrows(ResponseStatusException.class,()->service.command("000070",fill(2,"mark-older","MARK",10,0,11,"2026-10-13")));
        assertEquals(12,amount("last_mark"));
    }
    @Test void invalidRuntimeStateRollsBackFillAndCashTogether() {
        var state=mapper.createObjectNode().put("peak_high",9);
        var invalid=new StrategyBookService.Command(0L,"bad-state-buy","BUY",new BigDecimal("10"),100L,
            new BigDecimal("10"),"2026-10-12 10:00:00","2026-10-12 10:00:00",state,"test");
        assertThrows(ResponseStatusException.class,()->service.command("000070",invalid));
        assertTrue(service.books().isEmpty());
        assertTrue(service.events("000070").isEmpty());
    }
    @Test void simultaneousWritersCannotBothBuyTheSameBook() throws Exception {
        try (var executor=java.util.concurrent.Executors.newFixedThreadPool(2)) {
            var jobs=java.util.List.of("concurrent-a","concurrent-b").stream().map(id ->
                executor.submit(() -> {
                    try { service.command("000070",fill(0,id,"BUY",10,1000,10,"2026-10-12")); return true; }
                    catch (ResponseStatusException e) { return false; }
                })).toList();
            int successes=0;
            for (var job:jobs) if (job.get()) successes++;
            assertEquals(1,successes);
            assertEquals(1,service.events("000070").size());
            assertEquals(90000,amount("virtual_cash"));
        }
    }
}
