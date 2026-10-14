package com.myquan.backend.holdings;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.DeserializationFeature;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.HexFormat;
import java.util.Map;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

@Service
public class PaperStateService {
    public record State(long revision, JsonNode holdings, JsonNode trades, JsonNode ledger) {}
    public record Write(Long expectedRevision, String requestId, JsonNode holdings, JsonNode trades, JsonNode ledger) {}
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transactions;
    private final ObjectMapper mapper;
    private final HoldingsService holdingsService;
    private final Path source;

    public PaperStateService(JdbcTemplate jdbc, TransactionTemplate transactions, ObjectMapper mapper,
            HoldingsService holdingsService, @Value("${myquan.holdings.path:../holdingStocks/holdings.json}") String source) {
        this.jdbc = jdbc;
        this.transactions = transactions;
        this.mapper = mapper;
        this.holdingsService = holdingsService;
        this.source = Path.of(source);
    }

    public boolean initialized() {
        return jdbc.queryForObject("SELECT revision FROM paper_account_state WHERE id=1", Long.class) > 0;
    }

    public Map<String, Object> syncLegacy() {
        return transactions.execute(status -> {
            var row=jdbc.queryForMap("SELECT revision FROM paper_account_state WHERE id=1 FOR UPDATE");
            if (((Number)row.get("revision")).longValue()>0)
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Database is authoritative; local sync is disabled.");
            return holdingsService.sync();
        });
    }

    public State read() {
        var row = jdbc.queryForMap("SELECT * FROM paper_account_state WHERE id=1");
        if (((Number) row.get("revision")).longValue() == 0) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Database ledger has not been migrated.");
        }
        return decode(row);
    }

    private State decode(Map<String, Object> row) {
        try {
            return new State(((Number) row.get("revision")).longValue(), json(row.get("holdings").toString()),
                    json(row.get("trades").toString()), json(row.get("ledger").toString()));
        } catch (Exception exception) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Database ledger is invalid.");
        }
    }

    private JsonNode json(String text) throws java.io.IOException {
        return mapper.reader().with(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS).readTree(text);
    }

    public State migrate() {
        return transactions.execute(status -> {
            var row = jdbc.queryForMap("SELECT * FROM paper_account_state WHERE id=1 FOR UPDATE");
            if (((Number) row.get("revision")).longValue() != 0) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Migration already completed; local overwrite disabled.");
            }
            try {
                var holdings = json(Files.readString(source));
                var ledger = json(Files.readString(source.resolveSibling("trade_ledger.json")));
                var trades = mapper.createArrayNode();
                for (var line : Files.readAllLines(source.resolveSibling("trades.jsonl"))) {
                    if (!line.isBlank()) trades.add(json(line));
                }
                return write(new Write(0L, UUID.randomUUID().toString(), holdings, trades, ledger));
            } catch (java.io.IOException exception) {
                throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                        "Migration source missing or invalid; no database state changed.");
            }
        });
    }

    public State write(Write input) {
        if (input.expectedRevision() == null || input.requestId() == null
                || !input.requestId().matches("[a-zA-Z0-9_-]{1,64}") || input.expectedRevision() < 0)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Revision and request ID are required.");
        validate(input);
        String hash;
        try {
            hash = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(
                    mapper.writeValueAsBytes(input)));
        } catch (Exception exception) { throw new IllegalStateException(exception); }
        return transactions.execute(status -> {
            var current = jdbc.queryForMap("SELECT * FROM paper_account_state WHERE id=1 FOR UPDATE");
            long version = ((Number) current.get("revision")).longValue();
            var retries = jdbc.queryForList("SELECT * FROM paper_state_writes WHERE request_id=?", input.requestId());
            if (!retries.isEmpty()) {
                var prior = retries.getFirst();
                if (!hash.equals(prior.get("payload_hash")) || ((Number) prior.get("revision")).longValue() != version)
                    throw new ResponseStatusException(HttpStatus.CONFLICT, "Request already applied or reused; reload state.");
                return decode(current);
            }
            if (version != input.expectedRevision())
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Ledger revision changed; reload before modifying.");
            if (version > 0) validateHistory(decode(current), input);
            var now = Timestamp.valueOf(LocalDateTime.now(ZoneId.of("Asia/Shanghai")));
            jdbc.update("UPDATE paper_account_state SET revision=?, holdings=?, trades=?, ledger=?, updated_at=? WHERE id=1",
                    version + 1, input.holdings().toString(), input.trades().toString(), input.ledger().toString(), now);
            holdingsService.replaceProjection(input.holdings().get("positions"));
            jdbc.update("UPDATE paper_holdings_sync SET source_updated_at=NULL,source_digest=NULL,synced_at=? WHERE id=1", now);
            if (!input.trades().toString().equals(current.get("trades"))) {
                jdbc.update("DELETE FROM paper_trade_history");
                long sequence = 0;
                for (var record : input.trades()) {
                    jdbc.update("INSERT INTO paper_trade_history (sequence_no,code,side,executed_at,payload) VALUES (?,?,?,?,?)",
                            ++sequence, record.path("code").asText(""), record.path("side").asText(""),
                            record.path("time").asText(""), record.toString());
                }
            }
            if (!input.ledger().toString().equals(current.get("ledger"))) {
                jdbc.update("DELETE FROM paper_delivery_entries");
                long sequence = 0;
                for (var entry : input.ledger().get("entries")) {
                    jdbc.update("INSERT INTO paper_delivery_entries (sequence_no,entry_id,code,side,executed_at,payload) VALUES (?,?,?,?,?,?)",
                            ++sequence, entry.path("id").asText(""), entry.path("code").asText(""), entry.path("side").asText(""),
                            entry.path("time").asText(""), entry.toString());
                }
            }
            jdbc.update("INSERT INTO paper_state_writes (request_id,payload_hash,revision) VALUES (?,?,?)", input.requestId(), hash, version+1);
            return new State(version+1, input.holdings(), input.trades(), input.ledger());
        });
    }

    private void validateHistory(State current, Write input) {
        for (var entry:current.holdings().properties()) {
            if (!input.holdings().has(entry.getKey()))
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Partial account document rejected; preserve existing fields.");
        }
        if (input.trades().size() < current.trades().size()
                || input.ledger().get("entries").size() < current.ledger().get("entries").size())
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Committed history cannot be deleted.");
        for (int i=0; i<current.trades().size(); i++) {
            var before=current.trades().get(i).deepCopy();
            var after=input.trades().get(i).deepCopy();
            var previousFlag=before.path("reset_archived");
            var nextFlag=after.path("reset_archived");
            if (!previousFlag.equals(nextFlag) && !nextFlag.isBoolean())
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Invalid archive flag.");
            if (!previousFlag.equals(nextFlag) && !nextFlag.asBoolean())
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Archived trades cannot be reactivated.");
            ((com.fasterxml.jackson.databind.node.ObjectNode)before).remove("reset_archived");
            ((com.fasterxml.jackson.databind.node.ObjectNode)after).remove("reset_archived");
            if (!equivalent(before, after))
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Committed trades are immutable; append an adjustment.");
        }
        for (int i=0; i<current.ledger().get("entries").size(); i++) {
            if (!equivalent(current.ledger().get("entries").get(i), input.ledger().get("entries").get(i)))
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Committed deliveries are immutable.");
        }
    }

    private boolean equivalent(JsonNode first, JsonNode second) {
        if (first.isNumber() && second.isNumber())
            return first.decimalValue().compareTo(second.decimalValue()) == 0;
        if (first.isObject() && second.isObject()) {
            if (first.size() != second.size()) return false;
            for (var entry:first.properties()) {
                var other=second.get(entry.getKey());
                if (other == null || !equivalent(entry.getValue(),other)) return false;
            }
            return true;
        }
        if (first.isArray() && second.isArray()) {
            if (first.size() != second.size()) return false;
            for (int i=0;i<first.size();i++) if (!equivalent(first.get(i),second.get(i))) return false;
            return true;
        }
        return first.equals(second);
    }

    private void validate(Write input) {
        var holdings = input.holdings();
        if (holdings == null || !holdings.isObject() || !holdings.path("positions").isObject()
                || input.trades() == null || !input.trades().isArray()
                || input.ledger() == null || !input.ledger().isObject() || !input.ledger().path("entries").isArray())
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "Invalid ledger structure.");
        for (String key : new String[]{"account_cash", "account_total", "paper_equity_base"}) {
            var value = holdings.get(key);
            if (value != null && !value.isNull() && !value.isNumber())
                throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "Invalid account value.");
        }
        for (var entry : input.trades()) if (!entry.isObject())
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "Invalid trade record.");
        for (var entry : input.ledger().get("entries")) if (!entry.isObject())
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "Invalid delivery record.");
        holdingsService.validatePositions(holdings.get("positions"));
    }
}
