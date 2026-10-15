package com.myquan.backend.holdings;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
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
public class StrategyBookService {
    public record Command(Long expectedRevision, String requestId, String side, BigDecimal price,
            Long qty, BigDecimal mark, String quoteAt, String decisionAt, JsonNode state, String reason) {}
    private static final String SID="strategy16";
    private static final BigDecimal CAPITAL=new BigDecimal("100000");
    private static final DateTimeFormatter CLOCK=DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transactions;
    private final ObjectMapper mapper;
    private final java.util.function.Supplier<LocalDateTime> clock;
    @org.springframework.beans.factory.annotation.Autowired
    public StrategyBookService(JdbcTemplate jdbc, TransactionTemplate transactions, ObjectMapper mapper) {
        this(jdbc,transactions,mapper,()->LocalDateTime.now(ZoneId.of("Asia/Shanghai")));
    }
    StrategyBookService(JdbcTemplate jdbc, TransactionTemplate transactions, ObjectMapper mapper,
            java.util.function.Supplier<LocalDateTime> clock) {
        this.jdbc=jdbc; this.transactions=transactions;
        this.clock=clock;
        this.mapper=mapper.copy().enable(com.fasterxml.jackson.databind.DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS);
    }
    private void require(boolean valid, String message) {
        if (!valid) throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,message);
    }
    private void conflict(boolean valid, String message) {
        if (!valid) throw new ResponseStatusException(HttpStatus.CONFLICT,message);
    }
    private void symbol(String symbol) { require(symbol!=null && symbol.matches("[0-9]{6}"),"Invalid symbol"); }
    private ObjectNode parse(String raw) {
        try { return (ObjectNode)mapper.readTree(raw); }
        catch (Exception e) { throw new IllegalStateException("Invalid persisted strategy book",e); }
    }
    private String hash(Object value) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(mapper.writeValueAsBytes(value))); }
        catch (Exception e) { throw new IllegalStateException(e); }
    }
    private BigDecimal n(JsonNode book, String key) {
        var node=book.get(key);
        return node==null || node.isNull() ? BigDecimal.ZERO : node.decimalValue();
    }
    private BigDecimal pct(BigDecimal profit, BigDecimal basis) {
        return basis.signum()>0 ? profit.multiply(new BigDecimal("100")).divide(basis,6,RoundingMode.HALF_UP) : null;
    }
    private void put(ObjectNode node, String key, BigDecimal value) {
        if (value==null) node.putNull(key); else node.put(key,value);
    }
    private ObjectNode empty(String symbol) {
        var book=mapper.createObjectNode();
        book.put("strategy_id",SID).put("symbol",symbol).put("revision",0)
            .put("state","FLAT").put("initial_cash",CAPITAL).put("virtual_cash",CAPITAL)
            .put("virtual_shares",0).put("single_cost_base",0).put("single_realized_pnl",0)
            .put("single_sold_shares",0).put("trades",0).put("history_status","new_database_ledger");
        return book;
    }
    private ObjectNode locked(String symbol) {
        var rows=jdbc.queryForList("SELECT payload FROM strategy_symbol_books WHERE strategy_id=? AND symbol=? FOR UPDATE",SID,symbol);
        return rows.isEmpty() ? null : parse(rows.getFirst().get("PAYLOAD").toString());
    }
    private ObjectNode lockOrCreate(String symbol) {
        jdbc.update("INSERT IGNORE INTO strategy_symbol_books(strategy_id,symbol,revision,qty,payload) VALUES(?,?,0,0,?)",SID,symbol,empty(symbol).toString());
        return locked(symbol);
    }
    private void value(ObjectNode book, BigDecimal mark) {
        long qty=book.path("virtual_shares").asLong();
        BigDecimal entry=n(book,"entry_price"), initial=n(book,"initial_cash");
        // Cash conservation includes every sell leg; a price percentage is not account PnL.
        BigDecimal floating=qty>0 ? mark.subtract(entry).multiply(BigDecimal.valueOf(qty)) : BigDecimal.ZERO;
        BigDecimal realized=n(book,"virtual_cash").add(entry.multiply(BigDecimal.valueOf(qty))).subtract(initial);
        BigDecimal total=realized.add(floating);
        BigDecimal cycle=n(book,"single_realized_pnl").add(floating);
        book.put("last_mark",mark);
        book.put("unrealized_pnl",floating.setScale(2,RoundingMode.HALF_UP));
        book.put("realized_pnl",realized.setScale(2,RoundingMode.HALF_UP));
        book.put("total_pnl",total.setScale(2,RoundingMode.HALF_UP));
        book.put("cycle_pnl",cycle.setScale(2,RoundingMode.HALF_UP));
        book.put("since_checkpoint_pnl",total.subtract(n(book,"checkpoint_total_pnl")).setScale(2,RoundingMode.HALF_UP));
        put(book,"cumulative_return_pct",pct(total,initial));
        put(book,"cycle_return_pct",pct(cycle,n(book,"single_cost_base")));
        put(book,"single_return_pct",qty>0 ? pct(mark.subtract(entry),entry) : pct(cycle,n(book,"single_cost_base")));
    }
    private void save(String symbol, ObjectNode book) {
        jdbc.update("UPDATE strategy_symbol_books SET revision=?,qty=?,entry_price=?,last_price=?,total_pnl=?,cycle_pnl=?,payload=?,updated_at=CURRENT_TIMESTAMP WHERE strategy_id=? AND symbol=?",
            book.path("revision").asLong(),book.path("virtual_shares").asLong(),book.get("entry_price")==null?null:n(book,"entry_price"),
            book.get("last_mark")==null?null:n(book,"last_mark"),book.get("total_pnl")==null?null:n(book,"total_pnl"),
            book.get("cycle_pnl")==null?null:n(book,"cycle_pnl"),book.toString(),SID,symbol);
    }
    public Map<String,JsonNode> books() {
        var result=new LinkedHashMap<String,JsonNode>();
        jdbc.query("SELECT symbol,payload FROM strategy_symbol_books WHERE strategy_id=? ORDER BY symbol",
            rs -> { result.put(rs.getString("symbol"),parse(rs.getString("payload"))); },SID);
        return result;
    }
    public List<Map<String,Object>> events(String symbol) {
        symbol(symbol);
        return jdbc.queryForList("SELECT * FROM strategy_symbol_events WHERE strategy_id=? AND symbol=? ORDER BY book_revision",SID,symbol);
    }
    public JsonNode checkpoint(String symbol, JsonNode raw) {
        symbol(symbol);
        require(raw.isObject(),"Invalid checkpoint");
        require(raw.path("virtual_cash").isNumber() && raw.path("initial_cash").isNumber()
            && raw.path("virtual_shares").isNumber(),"Missing checkpoint amounts");
        BigDecimal quantity=n(raw,"virtual_shares");
        require(quantity.signum()>=0 && quantity.stripTrailingZeros().scale()<=0
            && quantity.compareTo(BigDecimal.valueOf(Long.MAX_VALUE))<0 && n(raw,"initial_cash").signum()>0
            && n(raw,"virtual_cash").signum()>=0,"Invalid checkpoint amounts");
        require(quantity.signum()==0 || n(raw,"entry_price").signum()>0,"Open checkpoint needs cost");
        return transactions.execute(tx -> {
            lockOrCreate(symbol);
            var old=jdbc.queryForList("SELECT source_hash FROM strategy_legacy_checkpoints WHERE strategy_id=? AND symbol=?",SID,symbol);
            if (!old.isEmpty()) {
                conflict(old.getFirst().get("SOURCE_HASH").equals(hash(raw)),"Different checkpoint already imported");
                return locked(symbol);
            }
            var current=locked(symbol);
            conflict(current.path("revision").asLong()==0,"Cannot overwrite an active strategy book");
            var book=(ObjectNode)raw.deepCopy();
            book.put("strategy_id",SID).put("symbol",symbol).put("revision",1)
                .put("virtual_shares",quantity.longValue()).put("history_status","legacy_checkpoint_unverified")
                .put("state",quantity.signum()>0?"LONG":"FLAT");
            BigDecimal entry=n(book,"entry_price"), basis=n(book,"single_cost_base");
            if (quantity.signum()>0 && basis.signum()<=0) book.put("single_cost_base",quantity.multiply(entry));
            var mark=n(book,"last_mark");
            if (mark.signum()<=0) mark=entry.signum()>0?entry:BigDecimal.ONE;
            value(book,mark);
            book.put("checkpoint_total_pnl",n(book,"total_pnl"));
            book.put("since_checkpoint_pnl",BigDecimal.ZERO);
            jdbc.update("INSERT INTO strategy_legacy_checkpoints(strategy_id,symbol,source_hash,payload) VALUES(?,?,?,?)",SID,symbol,hash(raw),raw.toString());
            save(symbol,book);
            return book;
        });
    }
    public JsonNode command(String symbol, Command input) {
        symbol(symbol);
        require(input.expectedRevision()!=null && input.expectedRevision()>=0 && input.requestId()!=null
            && input.requestId().matches("[a-zA-Z0-9_-]{8,64}") && input.side()!=null && List.of("BUY","SELL","MARK").contains(input.side())
            && input.mark()!=null && input.mark().signum()>0,"Invalid strategy command");
        LocalDateTime source,decision;
        try { source=LocalDateTime.parse(input.quoteAt(),CLOCK); decision=LocalDateTime.parse(input.decisionAt(),CLOCK); }
        catch (Exception e) { throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"Invalid quote/decision time"); }
        require(!source.isAfter(decision) && !decision.isAfter(clock.get().plusSeconds(5)),"Future quote/decision");
        if (!input.side().equals("MARK")) {
            require(source.toLocalDate().equals(decision.toLocalDate()),"Quote session mismatch");
            String clock=source.toLocalTime().toString();
            require((clock.compareTo("09:30")>=0 && clock.compareTo("11:30:00")<=0)
                || (clock.compareTo("13:00")>=0 && clock.compareTo("15:00")<0),"Fill outside continuous session");
            require(java.time.Duration.between(source,decision).toSeconds()<=5,"Stale fill quote");
        }
        final String digest=hash(Map.of("symbol",symbol,"command",input));
        return transactions.execute(tx -> {
            var book=lockOrCreate(symbol);
            var prior=jdbc.queryForList("SELECT payload_hash FROM strategy_symbol_events WHERE request_id=?",input.requestId());
            if (!prior.isEmpty()) {
                conflict(prior.getFirst().get("PAYLOAD_HASH").equals(digest),"Request ID payload changed");
                return book;
            }
            if (input.side().equals("MARK") && input.requestId().equals(book.path("last_mark_request").asText())) {
                conflict(digest.equals(book.path("last_mark_hash").asText()),"Mark request payload changed");
                return book;
            }
            conflict(book.path("revision").asLong()==input.expectedRevision(),"Strategy revision conflict");
            String previous=book.path("last_quote_ts").asText("");
            conflict(previous.isBlank() || input.quoteAt().compareTo(previous)>=0,"Older quote cannot overwrite strategy state");
            long held=book.path("virtual_shares").asLong();
            if (!input.side().equals("MARK")) {
                LiveFillGuard.check(input.quoteAt(),input.decisionAt(),clock.get());
                require(input.qty()!=null && input.qty()>0 && input.price()!=null && input.price().signum()>0,"Invalid fill amounts");
                BigDecimal amount=input.price().multiply(BigDecimal.valueOf(input.qty()));
                if (input.side().equals("BUY")) {
                    conflict(held==0,"Strategy already holding; pyramiding not enabled");
                    require(input.qty()%100==0,"Buy quantity must be whole lots");
                    conflict(n(book,"virtual_cash").compareTo(amount)>=0,"Strategy cash insufficient");
                    String exited=book.path("exit_time").asText("");
                    conflict(!exited.startsWith(input.quoteAt().substring(0,10)) || book.path("gap_rebuy_allowed").asBoolean(),"Same-day strategy rebuy blocked");
                    book.put("virtual_cash",n(book,"virtual_cash").subtract(amount)).put("virtual_shares",input.qty())
                        .put("entry_price",input.price()).put("entry_time",input.decisionAt()).put("state","LONG")
                        .put("single_cost_base",amount).put("single_realized_pnl",0).put("single_sold_shares",0)
                        .put("peak_high",input.price()).put("peak_high_at",input.quoteAt()).put("tp_stage",0).put("gap_rebuy_allowed",false);
                    for (String key:List.of("quote_exit_session","quote_session_peak","quote_exit_watermark","quote_cycle_low","stop_noted","stop_noted_px")) book.remove(key);
                } else {
                    conflict(held>=input.qty(),"Sell exceeds strategy position");
                    String bought=book.path("entry_time").asText("");
                    conflict(!bought.isBlank() && bought.substring(0,10).compareTo(input.quoteAt().substring(0,10))<0,"T+1 strategy position locked");
                    BigDecimal profit=input.price().subtract(n(book,"entry_price")).multiply(BigDecimal.valueOf(input.qty()));
                    boolean noted=book.path("stop_noted").asBoolean() || (input.state()!=null && input.state().path("stop_noted").asBoolean());
                    book.put("virtual_cash",n(book,"virtual_cash").add(amount)).put("virtual_shares",held-input.qty())
                        .put("single_realized_pnl",n(book,"single_realized_pnl").add(profit))
                        .put("single_sold_shares",book.path("single_sold_shares").asLong()+input.qty())
                        .put("exit_price",input.price()).put("exit_time",input.decisionAt())
                        .put("state",held==input.qty()?"FLAT":"LONG")
                        .put("gap_rebuy_allowed",held==input.qty() && noted && "open_protect".equals(input.reason()));
                    if (held>input.qty()) book.put("tp_stage",1);
                }
                book.put("trades",book.path("trades").asLong()+1);
            }
            if (input.state()!=null) {
                require(input.state().isObject(),"Invalid strategy runtime state");
                for (String key:List.of("peak_high","peak_high_at","quote_exit_session","quote_session_peak",
                        "quote_exit_watermark","quote_cycle_low","stop_noted","stop_noted_px","stop_noted_session","stop_note_source",
                        "overnight_peak","overnight_peak_session")) {
                    if (input.state().has(key)) {
                        var v=input.state().get(key);
                        if (key.equals("peak_high")) require(v.isNumber() && v.decimalValue().compareTo(n(book,key))>=0,"Peak cannot decrease");
                        if (key.equals("peak_high_at")) require(v.isTextual() && v.asText().compareTo(input.quoteAt())<=0,"Future peak time");
                        book.set(key,v);
                    }
                }
            }
            value(book,input.mark());
            book.put("last_quote_ts",input.quoteAt()).put("last_decision_at",input.decisionAt())
                .put("revision",book.path("revision").asLong()+1);
            if (input.side().equals("MARK")) {
                book.put("last_mark_request",input.requestId()).put("last_mark_hash",digest);
            } else {
                BigDecimal cost=n(book,"entry_price");
                BigDecimal profit=input.side().equals("SELL") ? input.price().subtract(cost).multiply(BigDecimal.valueOf(input.qty())) : BigDecimal.ZERO;
                jdbc.update("INSERT INTO strategy_symbol_events(request_id,strategy_id,symbol,payload_hash,side,price,qty,source_at,decision_at,payload,book_revision,cost_price,realized_pnl,after_qty,cash_after) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    input.requestId(),SID,symbol,digest,input.side(),input.price(),input.qty(),input.quoteAt(),input.decisionAt(),json(input),
                    book.path("revision").asLong(),cost,profit,book.path("virtual_shares").asLong(),n(book,"virtual_cash"));
            }
            if (!input.side().equals("MARK")) LiveFillGuard.check(input.quoteAt(),input.decisionAt(),clock.get());
            save(symbol,book);
            return book;
        });
    }
    private String json(Object input) {
        try { return mapper.writeValueAsString(input); }
        catch (Exception e) { throw new IllegalStateException(e); }
    }
}
