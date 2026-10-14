package com.myquan.backend.holdings;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.DeserializationFeature;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

@Service
public class HoldingsService {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transactions;
    private final ObjectMapper mapper;
    private final Path source;
    private static final DateTimeFormatter SOURCE_TIME = DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm:ss")
            .withResolverStyle(java.time.format.ResolverStyle.STRICT);

    public HoldingsService(JdbcTemplate jdbc, TransactionTemplate transactions, ObjectMapper mapper,
            @Value("${myquan.holdings.path:../holdingStocks/holdings.json}") String source) {
        this.jdbc = jdbc;
        this.transactions = transactions;
        this.mapper = mapper;
        this.source = Path.of(source);
    }

    public record Holding(String code, String name, String market, long qty, Long available,
            BigDecimal cost, String buyTime, BigDecimal peakHigh, String note) {}

    public Map<String, Object> snapshot() {
        return transactions.execute(status -> {
            var metadata = jdbc.queryForMap("SELECT * FROM paper_holdings_sync WHERE id = 1 FOR UPDATE");
            var positions = jdbc.queryForList("SELECT * FROM paper_holdings ORDER BY code");
            return Map.of("source", "paper-ledger", "metadata", metadata, "positions", positions,
                    "count", positions.size());
        });
    }

    public Map<String, Object> sync() {
        return transactions.execute(status -> {
            // Serialize snapshot reads and writes so concurrent requests cannot restore older holdings.
            var previous = jdbc.queryForMap("SELECT * FROM paper_holdings_sync WHERE id = 1 FOR UPDATE");
            byte[] bytes;
            JsonNode root;
            LocalDateTime updated;
            String digest;
            List<Holding> holdings;
            try {
                bytes = Files.readAllBytes(source);
                root = mapper.reader().with(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS).readTree(bytes);
                if (root == null || !root.isObject() || !root.path("positions").isObject()) {
                    throw new IllegalArgumentException();
                }
                updated = LocalDateTime.parse(root.path("updated_at").asText(), SOURCE_TIME);
                digest = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
                holdings = parse(root.get("positions"));
            } catch (Exception exception) {
                throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                        "Holdings source is missing or invalid; database snapshot was not changed.");
            }
            var oldTime = (Timestamp) previous.get("source_updated_at");
            if (oldTime != null && updated.isBefore(oldTime.toLocalDateTime())) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Older holdings snapshot rejected.");
            }
            if (digest.equals(previous.get("source_digest"))) {
                return Map.of("changed", false, "count", holdings.size(), "sourceUpdatedAt", updated);
            }
            jdbc.update("DELETE FROM paper_holdings");
            for (var holding : holdings) {
                jdbc.update("""
                        INSERT INTO paper_holdings (code, name, market, qty, available, cost, buy_time, peak_high, note)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, holding.code(), holding.name(), holding.market(), holding.qty(), holding.available(),
                        holding.cost(), holding.buyTime(), holding.peakHigh(), holding.note());
            }
            jdbc.update("UPDATE paper_holdings_sync SET source_updated_at=?, source_digest=?, synced_at=? WHERE id=1",
                    Timestamp.valueOf(updated), digest,
                    Timestamp.valueOf(LocalDateTime.now(ZoneId.of("Asia/Shanghai"))));
            return Map.of("changed", true, "count", holdings.size(), "sourceUpdatedAt", updated);
        });
    }

    private List<Holding> parse(JsonNode positions) {
        var result = new ArrayList<Holding>();
        positions.properties().forEach(entry -> {
            var code = entry.getKey();
            var value = entry.getValue();
            if (!code.matches("[0-9]{6}") || !value.isObject()) throw new IllegalArgumentException();
            long qty = quantity(value.get("qty"));
            if (qty == 0) return;
            Long available = value.hasNonNull("available") ? quantity(value.get("available")) : null;
            if (available != null && available > qty) throw new IllegalArgumentException();
            var cost = price(value.get("cost"));
            result.add(new Holding(code, value.path("name").asText(""), value.path("market").asText(""),
                    qty, available, cost, value.path("buy_time").asText(null),
                    value.hasNonNull("peak_high") ? price(value.get("peak_high")) : null,
                    value.path("note").asText(null)));
        });
        return result;
    }

    private long quantity(JsonNode node) {
        if (node == null || !node.isIntegralNumber() || !node.canConvertToLong() || node.longValue() < 0)
            throw new IllegalArgumentException();
        return node.longValue();
    }

    private BigDecimal price(JsonNode node) {
        if (node == null || !node.isNumber()) throw new IllegalArgumentException();
        var value = node.decimalValue();
        if (value.signum() <= 0 || value.scale() > 8 || value.precision() - value.scale() > 12)
            throw new IllegalArgumentException();
        return value;
    }
}
