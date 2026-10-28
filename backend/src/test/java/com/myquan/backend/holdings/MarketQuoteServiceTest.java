package com.myquan.backend.holdings;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.List;
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

class MarketQuoteServiceTest {
    private final ObjectMapper mapper=new ObjectMapper();
    private MarketQuoteService service;
    @BeforeEach void setup() {
        var ds=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1","sa","");
        new ResourceDatabasePopulator(new ClassPathResource("db/migration/V7__latest_market_quotes.sql")).execute(ds);
        service=new MarketQuoteService(new JdbcTemplate(ds),new TransactionTemplate(new DataSourceTransactionManager(ds)),mapper);
    }
    private ObjectNode quote(String time, double last) {
        return mapper.createObjectNode().put("session","2026-10-12").put("last_ts","2026-10-12 "+time)
            .put("_received_at","2026-10-12 "+time+".123456").put("_quote_source","sina_batch")
            .put("_source_time_verified",true).put("open",10).put("high",11).put("low",9)
            .put("last",last).put("prev_close",10);
    }
    @Test void quoteAdmissionAndOutOfOrderReplayAreIdempotent() {
        var q=quote("10:00:01",10.5);
        var first=service.write(List.of(new MarketQuoteService.Quote("sz000070",q))).getFirst();
        assertEquals(1,first.path("_database_quote_revision").asLong());
        var retry=q.deepCopy().put("_received_at","2026-10-12 10:00:02.123456");
        assertEquals(1,service.write(List.of(new MarketQuoteService.Quote("sz000070",retry))).getFirst().path("_database_quote_revision").asLong());
        service.write(List.of(new MarketQuoteService.Quote("sz000070",quote("10:00:00",10.1))));
        assertEquals(10.5,service.latest().get("sz000070").path("last").asDouble());
    }
    @Test void twoSameSecondPricesReturnBothCommittedVersionsInOrder() {
        var high=quote("10:00:01",10.5);
        var lower=quote("10:00:01",10.4).put("_received_at","2026-10-12 10:00:01.223456");
        var result=service.write(List.of(new MarketQuoteService.Quote("sz000070",high),new MarketQuoteService.Quote("sz000070",lower)));
        assertEquals(10.5,result.get(0).path("last").asDouble());
        assertEquals(10.4,result.get(1).path("last").asDouble());
        assertEquals(2,result.get(1).path("_database_quote_revision").asLong());
        assertEquals("sz000070",result.get(1).path("_database_quote_symbol").asText());
    }
    @Test void timestampedTencentFallbackCanBeCommitted() {
        var q=quote("10:00:01",10.5).put("_quote_source","tencent_batch");
        var result=service.write(List.of(new MarketQuoteService.Quote("sz000070",q))).getFirst();
        assertEquals("tencent_batch",result.path("_quote_source").asText());
        assertEquals(1,result.path("_database_quote_revision").asLong());
    }
    @Test void badQuoteCannotPartiallyWriteABatch() {
        var good=quote("10:00:01",10.5);
        var bad=quote("10:00:01",10.5).put("_source_time_verified",false);
        assertThrows(ResponseStatusException.class,()->service.write(List.of(
            new MarketQuoteService.Quote("sz000070",good),new MarketQuoteService.Quote("sh600330",bad))));
        assertTrue(service.latest().isEmpty());
        bad.put("_source_time_verified",true).put("high",10.1);
        assertThrows(ResponseStatusException.class,()->service.write(List.of(new MarketQuoteService.Quote("sh600330",bad))));
    }
}
