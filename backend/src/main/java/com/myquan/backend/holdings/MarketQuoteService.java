package com.myquan.backend.holdings;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

@Service
public class MarketQuoteService {
    public record Quote(String symbol, JsonNode quote) {}
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final ObjectMapper mapper;
    public MarketQuoteService(JdbcTemplate jdbc, TransactionTemplate tx, ObjectMapper mapper) {
        this.jdbc=jdbc; this.tx=tx; this.mapper=mapper;
    }
    private void require(boolean ok) {
        if (!ok) throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"Invalid source-timestamped quote");
    }
    private ObjectNode parse(Object value) {
        try { return (ObjectNode)mapper.readTree(value.toString()); }
        catch (Exception e) { throw new IllegalStateException(e); }
    }
    public Map<String,JsonNode> latest() {
        var result=new LinkedHashMap<String,JsonNode>();
        jdbc.query("SELECT symbol,payload FROM market_quote_latest WHERE revision>0 ORDER BY symbol",
            rs->{ result.put(rs.getString("symbol"),parse(rs.getString("payload"))); });
        return result;
    }
    private void validate(Quote input) {
        require(input!=null && input.symbol()!=null && input.symbol().matches("(sh|sz|bj)[0-9]{6}")
            && input.quote()!=null && input.quote().isObject());
        var q=input.quote();
        require(q.path("_source_time_verified").asBoolean(false)
            && List.of("sina_batch", "tencent_batch").contains(q.path("_quote_source").asText()));
        for (String key:List.of("open","high","low","last","prev_close"))
            require(q.path(key).isNumber() && q.path(key).decimalValue().signum()>0);
        var high=q.path("high").decimalValue(); var low=q.path("low").decimalValue();
        require(low.compareTo(q.path("open").decimalValue().min(q.path("last").decimalValue()))<=0
            && high.compareTo(q.path("open").decimalValue().max(q.path("last").decimalValue()))>=0);
        try {
            var source=LocalDateTime.parse(q.path("last_ts").asText().replace(' ','T'));
            var received=LocalDateTime.parse(q.path("_received_at").asText().replace(' ','T'));
            require(source.format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")).equals(q.path("last_ts").asText())
                && received.format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss.SSSSSS")).equals(q.path("_received_at").asText())
                && source.toLocalDate().toString().equals(q.path("session").asText())
                && !source.isAfter(received) && !received.isAfter(LocalDateTime.now(ZoneId.of("Asia/Shanghai")).plusSeconds(1)));
        } catch (ResponseStatusException e) { throw e; }
        catch (Exception e) { require(false); }
    }
    private String hash(JsonNode input) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(mapper.writeValueAsBytes(input))); }
        catch (Exception e) { throw new IllegalStateException(e); }
    }
    public List<JsonNode> write(List<Quote> batch) {
        require(batch!=null && !batch.isEmpty() && batch.size()<=64);
        batch.forEach(this::validate);
        return tx.execute(status->{
            var result=new ArrayList<JsonNode>();
            // Deterministic locking across batches while preserving event order in the response.
            batch.stream().map(Quote::symbol).distinct().sorted().forEach(symbol->{
                jdbc.update("INSERT IGNORE INTO market_quote_latest(symbol,revision,source_at,received_at,payload_hash,payload) VALUES(?,0,'','','','{}')",symbol);
                jdbc.queryForList("SELECT symbol FROM market_quote_latest WHERE symbol=? FOR UPDATE",symbol);
            });
            for (var input:batch) {
                var old=jdbc.queryForMap("SELECT * FROM market_quote_latest WHERE symbol=?",input.symbol());
                var payload=(ObjectNode)input.quote().deepCopy();
                var identity=payload.deepCopy(); identity.remove("_received_at");
                String digest=hash(identity), source=payload.path("last_ts").asText(), receipt=payload.path("_received_at").asText();
                long revision=((Number)old.get("revision")).longValue();
                if (revision>0 && (source.compareTo(old.get("source_at").toString())<0
                        || (source.equals(old.get("source_at")) && (digest.equals(old.get("payload_hash"))
                            || receipt.compareTo(old.get("received_at").toString())<=0)))) {
                    result.add(parse(old.get("payload"))); continue;
                }
                payload.put("_database_quote_revision",revision+1);
                payload.put("_database_quote_symbol",input.symbol());
                payload.put("_database_quote_at",LocalDateTime.now(ZoneId.of("Asia/Shanghai")).toString());
                jdbc.update("UPDATE market_quote_latest SET revision=?,source_at=?,received_at=?,payload_hash=?,payload=?,updated_at=CURRENT_TIMESTAMP WHERE symbol=?",
                    revision+1,source,receipt,digest,payload.toString(),input.symbol());
                result.add(payload);
            }
            return result;
        });
    }
}
