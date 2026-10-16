package com.myquan.backend.holdings;

import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

@Service
public class AccountHistoryService {
    public record Sample(LocalDate tradingDay, LocalDateTime observedAt, Long revision,
            JsonNode account, JsonNode holdings, JsonNode closed) {}
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transactions;
    private final PaperStateService state;

    public AccountHistoryService(JdbcTemplate jdbc, TransactionTemplate transactions, PaperStateService state) {
        this.jdbc=jdbc;
        this.transactions=transactions;
        this.state=state;
    }

    public Map<String, Object> record(Sample sample) {
        if (sample.tradingDay()==null || sample.observedAt()==null || sample.revision()==null
                || sample.account()==null || !sample.account().isObject()
                || sample.holdings()==null || !sample.holdings().isArray()
                || sample.closed()==null || !sample.closed().isArray())
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"Invalid account snapshot.");
        var total=number(sample.account(),"accountTotal");
        var cash=number(sample.account(),"availableCash");
        var pnl=number(sample.account(),"totalPnl");
        if (total==null || cash==null || pnl==null)
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"Account valuation is not ready.");
        return transactions.execute(status -> {
            jdbc.queryForMap("SELECT revision FROM paper_account_state WHERE id=1 FOR UPDATE");
            var current=state.read();
            var storedSession=current.holdings().path("last_session").asText();
            boolean sameSession=sample.tradingDay().toString().equals(storedSession);
            // Valuation is read-only; legacy session metadata may lag committed fills.
            boolean liveSession=sample.tradingDay().equals(LocalDate.now(java.time.ZoneId.of("Asia/Shanghai")))
                    && sample.tradingDay().toString().compareTo(storedSession)>0
                    && sample.observedAt().toLocalDate().equals(sample.tradingDay());
            if ((!sameSession && !liveSession)
                    || sample.observedAt().toLocalDate().isBefore(sample.tradingDay())
                    || sample.observedAt().isAfter(LocalDateTime.now(java.time.ZoneId.of("Asia/Shanghai")).plusSeconds(30)))
                throw new ResponseStatusException(HttpStatus.CONFLICT,"Snapshot trading day/time is invalid.");
            if (sample.revision()<=0 || sample.revision()!=current.revision()
                    || current.holdings().path("account_cash").isNull()
                    || current.holdings().path("account_cash").isMissingNode()
                    || current.holdings().path("account_cash").decimalValue().compareTo(cash)!=0)
                throw new ResponseStatusException(HttpStatus.CONFLICT,"Snapshot cash/revision no longer matches the account.");
            var seen=new HashSet<String>();
            var positions=current.holdings().get("positions");
            var valuedMarket=BigDecimal.ZERO;
            for (var row:sample.holdings()) {
                var code=row.path("代码").asText();
                var pos=positions.get(code);
                if (!seen.add(code) || pos==null || !row.path("持仓").isIntegralNumber()
                        || row.path("持仓").longValue()<=0 || row.path("持仓").longValue()!=pos.path("qty").longValue()
                        || number(row,"现价")==null || number(row,"现价").signum()<=0
                        || number(row,"成本")==null || number(row,"成本").compareTo(pos.path("cost").decimalValue())!=0)
                    throw new ResponseStatusException(HttpStatus.CONFLICT,"Snapshot holdings/quotes do not match the account.");
                valuedMarket=valuedMarket.add(number(row,"现价").multiply(BigDecimal.valueOf(row.path("持仓").longValue())));
            }
            for (var entry:positions.properties()) {
                if (entry.getValue().path("qty").asLong()>0 && !seen.contains(entry.getKey()))
                    throw new ResponseStatusException(HttpStatus.CONFLICT,"Snapshot is missing an open position.");
            }
            // Empty inventory is genuinely 0%; absent valuation with open inventory is never 0%.
            var positionPct=seen.isEmpty() ? BigDecimal.ZERO : number(sample.account(),"positionPct");
            var marketValue=seen.isEmpty() ? BigDecimal.ZERO : number(sample.account(),"marketValue");
            if (seen.isEmpty() && number(sample.account(),"marketValue")!=null
                    && number(sample.account(),"marketValue").signum()!=0)
                throw new ResponseStatusException(HttpStatus.CONFLICT,"Flat account cannot carry a stale market value.");
            if (positionPct==null || marketValue==null)
                throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"Position valuation is missing.");
            if (valuedMarket.subtract(marketValue).abs().compareTo(new BigDecimal("0.01"))>0
                    || cash.add(valuedMarket).subtract(total).abs().compareTo(new BigDecimal("0.01"))>0
                    || positionPct.signum()<0)
                throw new ResponseStatusException(HttpStatus.CONFLICT,"Snapshot equity/market value does not reconcile.");
            var base=current.holdings().get("paper_equity_base");
            if (base!=null && base.isNumber() && total.subtract(base.decimalValue()).subtract(pnl).abs().compareTo(new BigDecimal("0.01"))>0)
                throw new ResponseStatusException(HttpStatus.CONFLICT,"Snapshot total return does not reconcile.");
            if (total.signum()>0 && positionPct.subtract(marketValue.multiply(new BigDecimal("100")).divide(total,8,java.math.RoundingMode.HALF_UP)).abs().compareTo(new BigDecimal("0.051"))>0)
                throw new ResponseStatusException(HttpStatus.CONFLICT,"Snapshot position percentage does not reconcile.");
            for (var row:sample.closed()) {
                if (!row.isObject() || row.path("持仓").asLong(-1)!=0 || !row.path("已实现").asBoolean())
                    throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"Invalid closed-position snapshot row.");
            }
            String key=sample.tradingDay()+":"+sample.observedAt().format(DateTimeFormatter.ofPattern("uuuuMMddHHmm"));
            var existing=jdbc.query("SELECT observed_at FROM paper_account_snapshots WHERE snapshot_key=?",
                    (rs, rowNum) -> rs.getTimestamp("observed_at").toLocalDateTime(),key);
            if (!existing.isEmpty()) {
                var previous=existing.getFirst();
                if (!sample.observedAt().isAfter(previous)) return Map.of("recorded",false,"key",key);
                jdbc.update("DELETE FROM paper_account_snapshots WHERE snapshot_key=?",key);
            }
            var recordedAccount=(com.fasterxml.jackson.databind.node.ObjectNode)sample.account().deepCopy();
            recordedAccount.put("positionPct",positionPct);
            recordedAccount.put("marketValue",marketValue);
            jdbc.update("""
                    INSERT INTO paper_account_snapshots (snapshot_key,trading_day,observed_at,account_revision,
                    total_pnl,total_pnl_pct,day_pnl,day_pnl_pct,position_pct,account_total,account_cash,market_value,
                    account_payload,holdings_payload,closed_payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,key,sample.tradingDay(),sample.observedAt(),sample.revision(),pnl,
                    number(sample.account(),"totalPnlPct"),number(sample.account(),"dayPnl"),number(sample.account(),"dayPnlPct"),
                    positionPct,total,cash,marketValue,recordedAccount.toString(),sample.holdings().toString(),sample.closed().toString());
            return Map.of("recorded",true,"key",key);
        });
    }

    private BigDecimal number(JsonNode node, String key) {
        var value=node.get(key);
        if (value==null || value.isNull()) return null;
        if (!value.isNumber()) throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"Invalid numeric snapshot field.");
        return value.decimalValue();
    }

    public List<Map<String,Object>> snapshots(LocalDate day, int limit) {
        int bounded=Math.max(1,Math.min(limit,1000));
        return day==null
                ? jdbc.queryForList("SELECT * FROM paper_account_snapshots ORDER BY observed_at DESC LIMIT ?",bounded)
                : jdbc.queryForList("SELECT * FROM paper_account_snapshots WHERE trading_day=? ORDER BY observed_at DESC LIMIT ?",day,bounded);
    }

    public List<Map<String,Object>> calendar(int year) {
        if (year<2000 || year>2100) throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"Invalid year");
        return jdbc.queryForList("""
            SELECT s.trading_day,s.day_pnl,s.day_pnl_pct,s.account_total,s.total_pnl,s.observed_at
            FROM paper_account_snapshots s
            WHERE s.trading_day>=? AND s.trading_day<? AND NOT EXISTS (
                SELECT 1 FROM paper_account_snapshots newer WHERE newer.trading_day=s.trading_day
                AND newer.observed_at>s.observed_at)
            ORDER BY s.trading_day
            """, LocalDate.of(year,1,1),LocalDate.of(year+1,1,1));
    }

    public List<Map<String,Object>> closed(LocalDate day, int limit) {
        int bounded=Math.max(1,Math.min(limit,1000));
        return day==null
                ? jdbc.queryForList("SELECT * FROM paper_closed_trades ORDER BY sequence_no DESC LIMIT ?",bounded)
                : jdbc.queryForList("SELECT * FROM paper_closed_trades WHERE executed_at LIKE ? ORDER BY sequence_no DESC LIMIT ?",day+"%",bounded);
    }
}
