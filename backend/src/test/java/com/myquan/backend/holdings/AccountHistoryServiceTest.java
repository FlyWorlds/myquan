package com.myquan.backend.holdings;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class AccountHistoryServiceTest {
    private final ObjectMapper mapper=new ObjectMapper();
    private JdbcTemplate jdbc;
    private PaperStateService state;
    private AccountHistoryService service;

    @BeforeEach
    void setup() throws Exception {
        var ds=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1","sa","");
        jdbc=new JdbcTemplate(ds);
        jdbc.execute("CREATE TABLE paper_account_state(id INT PRIMARY KEY,revision BIGINT)");
        jdbc.execute("INSERT INTO paper_account_state VALUES(1,1)");
        jdbc.execute("CREATE TABLE paper_account_snapshots(snapshot_key VARCHAR(64) PRIMARY KEY,trading_day DATE,observed_at TIMESTAMP,account_revision BIGINT,total_pnl DECIMAL(20,2),total_pnl_pct DECIMAL(12,6),day_pnl DECIMAL(20,2),day_pnl_pct DECIMAL(12,6),position_pct DECIMAL(12,6),account_total DECIMAL(20,2),account_cash DECIMAL(20,2),market_value DECIMAL(20,2),account_payload TEXT,holdings_payload TEXT,closed_payload TEXT)");
        state=mock(PaperStateService.class);
        when(state.read()).thenReturn(new PaperStateService.State(1,
                mapper.readTree("{\"account_cash\":100,\"paper_equity_base\":1000,\"last_session\":\"2026-10-14\",\"positions\":{\"002841\":{\"qty\":100,\"cost\":9}}}"),
                mapper.readTree("[]"),mapper.readTree("{\"entries\":[]}")));
        service=new AccountHistoryService(jdbc,new TransactionTemplate(new DataSourceTransactionManager(ds)),state);
    }

    private AccountHistoryService.Sample sample() throws Exception {
        return new AccountHistoryService.Sample(LocalDate.parse("2026-10-14"),LocalDateTime.parse("2026-10-14T15:36:00"),1L,
                mapper.readTree("{\"accountTotal\":1100,\"availableCash\":100,\"totalPnl\":100,\"totalPnlPct\":10,\"dayPnl\":null,\"dayPnlPct\":null,\"positionPct\":90.9,\"marketValue\":1000}"),
                mapper.readTree("[{\"代码\":\"002841\",\"持仓\":100,\"现价\":10,\"成本\":9}]"),mapper.readTree("[]"));
    }

    @Test
    void calendarUsesLastSnapshotWithoutSummingIntradayOrFillingMissingDays() throws Exception {
        service.record(sample());
        jdbc.update("UPDATE paper_account_snapshots SET day_pnl=10");
        var s=sample();
        service.record(new AccountHistoryService.Sample(s.tradingDay(),s.observedAt().plusMinutes(1),s.revision(),s.account(),s.holdings(),s.closed()));
        jdbc.update("UPDATE paper_account_snapshots SET day_pnl=25 WHERE observed_at=?",s.observedAt().plusMinutes(1));
        var rows=service.calendar(2026);
        assertEquals(1,rows.size());
        assertEquals("25.00", rows.getFirst().get("DAY_PNL").toString());
        assertTrue(service.calendar(2025).isEmpty());
    }

    @Test
    void snapshotStoresMoneyAndPercentSeparatelyAndDeduplicatesMinute() throws Exception {
        assertEquals(true,service.record(sample()).get("recorded"));
        assertEquals(false,service.record(sample()).get("recorded"));
        var rows=service.snapshots(LocalDate.parse("2026-10-14"),10);
        assertEquals(1,rows.size());
        assertEquals("100.00",rows.getFirst().get("TOTAL_PNL").toString());
        assertNull(rows.getFirst().get("DAY_PNL"));
    }

    @Test
    void mismatchingCashOrMissingInventoryDoesNotRecord() throws Exception {
        var s=sample();
        ((com.fasterxml.jackson.databind.node.ObjectNode)s.account()).put("availableCash",99);
        assertThrows(ResponseStatusException.class,()->service.record(s));
        var good=sample();
        assertThrows(ResponseStatusException.class,()->service.record(new AccountHistoryService.Sample(good.tradingDay(),good.observedAt(),1L,good.account(),mapper.createArrayNode(),good.closed())));
        assertEquals(0,service.snapshots(null,10).size());
    }

    @Test
    void zeroInventoryProducesGenuineZeroPositionWithoutInventingDayPnl() throws Exception {
        when(state.read()).thenReturn(new PaperStateService.State(1,
                mapper.readTree("{\"account_cash\":1000,\"paper_equity_base\":1000,\"last_session\":\"2026-10-14\",\"positions\":{}}"),mapper.readTree("[]"),mapper.readTree("{\"entries\":[]}")));
        var s=sample();
        var account=mapper.readTree("{\"accountTotal\":1000,\"availableCash\":1000,\"totalPnl\":0,\"positionPct\":null,\"marketValue\":null}");
        service.record(new AccountHistoryService.Sample(s.tradingDay(),s.observedAt(),1L,account,mapper.createArrayNode(),mapper.createArrayNode()));
        var row=service.snapshots(null,1).getFirst();
        assertEquals("0.000000",row.get("POSITION_PCT").toString());
        assertNull(row.get("DAY_PNL"));
    }

    @Test
    void sameCashAndQuantityCannotMakeAnOlderRevisionValid() throws Exception {
        var previous=state.read();
        when(state.read()).thenReturn(new PaperStateService.State(2,previous.holdings(),previous.trades(),previous.ledger()));
        assertThrows(ResponseStatusException.class,()->service.record(sample()));
        assertEquals(0,service.snapshots(null,1).size());
    }
}
