package com.myquan.backend.holdings;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

@Service
public class StrategySimVoidService {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transactions;
    private final ObjectMapper mapper;

    public StrategySimVoidService(JdbcTemplate jdbc, TransactionTemplate transactions, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.transactions = transactions;
        this.mapper = mapper;
    }

    public Map<String, Object> append(JsonNode body) {
        var events = body == null ? null : body.get("events");
        if (events == null || !events.isArray() || events.size() > 500)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Provide 1 to 500 voided events.");
        return transactions.execute(status -> {
            int inserted = 0;
            for (var event : events) {
                if (!event.isObject())
                    throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Each voided event must be an object.");
                String id = event.path("event_id").asText("");
                if (!id.matches("[A-Za-z0-9_-]{8,64}"))
                    throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Voided event id is invalid.");
                var existing = jdbc.queryForList("SELECT event_id FROM strategy_sim_voided_events WHERE event_id=?", id);
                if (!existing.isEmpty()) continue;
                jdbc.update("""
                        INSERT INTO strategy_sim_voided_events
                        (event_id, strategy_id, symbol, side, session_date, payload)
                        VALUES (?,?,?,?,?,?)
                        """, id, clip(event.path("strategy_id").asText(""), 32),
                        clip(event.path("symbol").asText(""), 16),
                        clip(event.path("side").asText(""), 8),
                        session(event), event.toString());
                inserted++;
            }
            return Map.of("inserted", inserted, "received", events.size());
        });
    }

    public Map<String, Object> count() {
        var count = jdbc.queryForObject("SELECT COUNT(*) FROM strategy_sim_voided_events", Long.class);
        return Map.of("count", count == null ? 0 : count);
    }

    private String session(JsonNode event) {
        String raw = event.path("trading_session_date").asText(event.path("trigger_time").asText(""));
        return raw.length() >= 10 && raw.substring(0, 10).matches("\\d{4}-\\d{2}-\\d{2}") ? raw.substring(0, 10) : null;
    }

    private String clip(String value, int max) {
        return value.length() <= max ? value : value.substring(0, max);
    }
}
