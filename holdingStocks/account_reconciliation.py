"""Pure committed-state read models; adjustments never rewrite source fills or cash."""
from __future__ import annotations

import copy
import math
import re
from paper_costs import MODEL as COST_MODEL
from typing import Any


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def enrich_snapshot_trade_metadata(snapshot, state):
    """Read-only display metadata from the same committed account revision."""
    if snapshot.get("paperRevision") != state["revision"]:
        return False
    day = str(snapshot.get("clock") or "")[:10]
    if not day:
        return False
    opened = sorted({str(t["code"]) for t in state.get("trades", [])
                     if t.get("code") and str(t.get("side") or "").lower() == "buy"
                     and not t.get("reset_archived")
                     and str(t.get("session") or t.get("time") or "")[:10] == day})
    slots = snapshot.setdefault("slotMeta", {})
    left = max(0, int(slots.get("maxNewSymbolsPerSession") or 2) - len(opened))
    values = dict(buysToday=len(opened), newSymbolsToday=opened,
                  buysLeft=left, newSymbolsLeft=left, session=day)
    changed = any(slots.get(k) != v for k, v in values.items())
    slots.update(values)
    closed = state["holdings"].get("realized_today") or {}
    for row in snapshot.get("holdings", []):
        rec = closed.get(row.get("代码"), {})
        if (int(row.get("持仓") or 0) > 0 or not row.get("已实现")
                or rec.get("session") != day):
            continue
        signal = rec.get("signal_time") or rec.get("first_hit_ts")
        if signal and str(signal).startswith(day):
            changed = changed or row.get("信号时间") != signal or row.get("卖信号时间") != signal
            row.update(信号时间=signal, 卖信号时间=signal)
    return changed


def effective_deliveries(state: dict[str, Any]):
    entries = copy.deepcopy(state["ledger"].get("entries", []))
    issues = []
    seen = set()
    for i, trade in enumerate(state.get("trades", [])):
        if trade.get("side") != "adjust" or trade.get("reset_archived"):
            continue
        ref = trade.get("adjusts_entry_id")
        old_price = number(trade.get("previous_price"))
        new_price = number(trade.get("price"))
        if not ref and trade.get("adjustment_kind") == "open_protect_reprice":
            # Compatibility for pre-migration records without an explicit fill ID.
            match = re.search(r"纠价 ([0-9.]+)->([0-9.]+)", str(trade.get("note", "")))
            if match:
                old_price = number(match[1])
        if trade.get("adjustment_kind") != "open_protect_reprice":
            issues.append({"kind": "unsupported_adjustment", "trade_index": i})
            continue
        candidates = [e for e in entries if e.get("side") == "sell"
                      and e.get("code") == trade.get("code")
                      and e.get("qty") == trade.get("qty")
                      and (not ref or e.get("id") == ref)
                      and old_price is not None and number(e.get("price")) == old_price
                      and str(e.get("time", "")) <= str(trade.get("time", ""))]
        token = str(trade.get("id") or f"legacy:{i}")
        if len(candidates) != 1 or new_price is None or new_price <= 0 or token in seen:
            issues.append({"kind": "ambiguous_adjustment", "trade_index": i, "candidates": len(candidates)})
            continue
        entry = candidates[0]
        qty = number(entry.get("qty"))
        cost = number(entry.get("cost"))
        if qty is None or qty <= 0 or cost is None or cost <= 0:
            issues.append({"kind": "invalid_adjustment_basis", "trade_index": i})
            continue
        delta = round((new_price - old_price) * qty, 2)
        expected_pnl = round((new_price - cost) * qty, 2)
        if number(trade.get("pnl")) is not None and abs(float(trade["pnl"]) - expected_pnl) > .01:
            issues.append({"kind": "adjustment_pnl_mismatch", "trade_index": i})
            continue
        seen.add(token)
        entry.setdefault("original_price", entry["price"])
        entry.setdefault("original_pnl", entry.get("pnl"))
        entry["price"] = new_price
        entry["amount"] = round(new_price * qty, 2)
        entry["pnl"] = expected_pnl
        entry["pnl_pct"] = round(expected_pnl / (cost * qty) * 100, 2)
        if number(entry.get("day_pnl")) is not None:
            entry["day_pnl"] = round(float(entry["day_pnl"]) + delta, 2)
            entry["day_pnl_pct"] = None  # Old rounded percentages do not define an exact denominator.
        entry.setdefault("adjustment_ids", []).append(token)
        entry["pnl_basis"] = "committed_fill_plus_adjustments"
    return entries, issues


class AccountReadModel:
    """Revision-scoped read model; corrected entries are indexed once, never written."""
    def __init__(self, state):
        self.state = state
        self.entries, self.issues = effective_deliveries(state)
        self.by_code = {}
        for entry in self.entries:
            self.by_code.setdefault(entry.get("code"), []).append(entry)

    def cycle_return(self, row):
        return cycle_return(self.state, row, read_model=self)


def account_summary(state: dict[str, Any], rows: list[dict[str, Any]], session: str, *, read_model=None):
    from strategy.akq_math import session_day_pnl
    book = state["holdings"]
    model = read_model or AccountReadModel(state)
    entries, issues = model.entries, list(model.issues)
    by_code = {}
    for row in rows:
        if row.get("代码") in by_code and int(row.get("持仓") or 0) > 0:
            issues.append({"kind": "duplicate_position_quote", "code": row["代码"]})
        if int(row.get("持仓") or 0) > 0:
            by_code[row.get("代码")] = row
    market = 0.0
    daily = 0.0
    valuation_ready = True
    daily_ready = not issues
    expected_codes = {code for code, pos in book.get("positions", {}).items() if int(pos.get("qty") or 0) > 0}
    if set(by_code) != expected_codes or any(e["kind"] == "duplicate_position_quote" for e in issues):
        valuation_ready = daily_ready = False
    cost_total = 0.0
    for code, pos in book.get("positions", {}).items():
        qty = int(pos.get("qty") or 0)
        if qty <= 0:
            continue
        row = by_code.get(code, {})
        mark, cost = number(row.get("现价")), number(pos.get("cost"))
        if (int(row.get("持仓") or 0) != qty or mark is None or mark <= 0
                or cost is None or cost <= 0 or number(row.get("成本")) != cost or row.get("error")):
            valuation_ready = daily_ready = False
            continue
        market += mark * qty
        cost_total += cost * qty
        value, _, _ = session_day_pnl(mark=mark, qty=qty, cost=cost,
                prev_close=row.get("昨收"), bought_today=str(pos.get("buy_time") or "")[:10] == session,
                fallback=None)
        if value is None:
            daily_ready = False
        else:
            daily += float(value) - (float(pos.get('buy_fees_remaining') or 0)
                if str(pos.get('buy_time') or '')[:10] == session else 0)
    sales = [e for e in entries if e.get("side") == "sell"
             and str(e.get("session") or e.get("time", ""))[:10] == session]
    if any(number(e.get("day_pnl")) is None for e in sales):
        daily_ready = False
    realized_day = sum(number(e.get("day_pnl")) or 0 for e in sales)
    cash, base = number(book.get("account_cash")), number(book.get("paper_equity_base"))
    total = round(cash + market, 2) if cash is not None and valuation_ready else None
    pnl = round(total - base, 2) if total is not None and base is not None and base > 0 else None
    anchor = number(book.get("account_total_open")) if book.get("account_total_open_session") == session else None
    day = round(daily + realized_day, 2) if daily_ready else None
    # Read-only rollover: committed cash + complete daily fills/quotes also
    # determine opening equity. Never reuse yesterday's opening balance.
    if anchor is None and total is not None and day is not None:
        inferred_open = round(total - day, 2)
        if inferred_open > 0:
            anchor = inferred_open
    return dict(accountTotal=total, availableCash=cash, marketValue=round(market, 2) if valuation_ready else None,
                feeModel=COST_MODEL,
                cost=round(cost_total, 2) if valuation_ready else None,
                paperEquityBase=base, totalPnl=pnl,
                totalPnlPct=round(pnl / base * 100, 2) if pnl is not None else None,
                dayPnl=day, dayPnlPct=round(day / anchor * 100, 2) if day is not None and anchor and anchor > 0 else None,
                accountOpen=anchor, positionPct=0.0 if not expected_codes else (round(market / total * 100, 1) if total and total > 0 else None),
                settledCount=len(sales), settledPnl=round(sum(number(e.get("pnl")) or 0 for e in sales), 2),
                settledDayPnl=round(realized_day, 2) if daily_ready else None,
                settledSession=session, equityBasis="cash_plus_market_value",
                dayPnlBasis="committed_fills_and_adjustments_plus_position_daily_pnl",
                paperRevision=state["revision"], reconciliationIssues=issues,
                equityDayPnl=round(total - anchor, 2) if total is not None and anchor is not None else None,
                dayPnlVsEquity=round(day - (total - anchor), 2) if day is not None and total is not None and anchor is not None else None)


def cycle_return(state, row, *, read_model=None):
    code = str(row.get("代码") or row.get("code") or "")
    model = read_model or AccountReadModel(state)
    if model.issues:
        return None
    entries = model.by_code.get(code, [])
    pos = state["holdings"].get("positions", {}).get(code, {})
    qty = int(pos.get("qty") or 0)
    hint = str(pos.get("buy_time") or "") if qty > 0 else str(
        (state["holdings"].get("realized_today", {}).get(code) or {}).get("buy_time") or "")
    buys = [e for e in entries if e.get("code") == code and e.get("side") == "buy"
            and (not hint or e.get("time") == hint)]
    if not buys:
        return None
    buy = max(buys, key=lambda e: str(e.get("time", "")))
    sales = [e for e in entries if e.get("code") == code and e.get("side") == "sell"
             and str(e.get("time", "")) >= str(buy["time"])
             and (not e.get("buy_time") or e.get("buy_time") == buy["time"])]
    if sum(int(e.get("qty") or 0) for e in sales) + qty != int(buy.get("qty") or 0):
        return None  # Incomplete/duplicated history must not produce a plausible percentage.
    base = (number(buy.get("amount")) or 0) + (number(buy.get("total_fees")) or 0)
    mark, cost = number(row.get("现价")), number(pos.get("cost"))
    if not base or base <= 0 or any(number(e.get("pnl")) is None for e in sales):
        return None
    if qty > 0 and (mark is None or mark <= 0 or cost is None or cost <= 0):
        return None
    pnl = sum(float(e["pnl"]) for e in sales) + ((mark - cost) * qty - float(pos.get('buy_fees_remaining') or 0) if qty > 0 else 0)
    return dict(pnl=round(pnl, 2), pnl_pct=round(pnl / base * 100, 2), base=base,
                sold_qty=sum(int(e["qty"]) for e in sales), open_qty=qty, buy_time=buy["time"],
                buy_price=buy["price"], legs=len(sales) + (1 if qty else 0),
                source="database_delivery_cycle_with_adjustments", paperRevision=state["revision"])
