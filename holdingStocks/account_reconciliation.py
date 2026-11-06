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
        if trade.get("adjustment_kind") == "session_replay":
            refs = trade.get("voided_delivery_ids")
            replacements = trade.get("replacement_delivery_ids")
            day = str(trade.get("session") or "")[:10]
            by_id = {e.get("id"): e for e in entries}
            archived = {t.get("id") for t in state.get("trades", []) if t.get("reset_archived")}
            valid = (isinstance(refs, list) and bool(refs) and isinstance(replacements, list)
                     and bool(replacements) and len(set(refs)) == len(refs)
                     and len(set(replacements)) == len(replacements)
                     and not set(refs).intersection(replacements) and len(day) == 10
                     and all(ref in by_id and ref in archived for ref in refs)
                     and all(ref in by_id for ref in replacements))
            if valid:
                valid = all(str(by_id[ref].get("session") or by_id[ref].get("time") or "")[:10] == day
                            and by_id[ref].get("side") in ("buy", "sell") for ref in refs + replacements)
            if not valid:
                issues.append({"kind": "invalid_session_replay", "trade_index": i})
                continue
            entries = [e for e in entries if e.get("id") not in set(refs)]
            continue
        if trade.get("adjustment_kind") == "buy_signal_restate":
            matches = [e for e in entries if e.get("id") == trade.get("adjusts_entry_id")
                       and e.get("side") == "buy" and e.get("code") == trade.get("code")
                       and e.get("qty") == trade.get("qty")]
            replacement = trade.get("replacement_delivery")
            if (len(matches) != 1 or not isinstance(replacement, dict)
                    or any(replacement.get(k) != matches[0].get(k) for k in ("id", "code", "side", "qty", "after_qty"))
                    or not number(replacement.get("price")) or number(replacement["price"]) <= 0
                    or str(replacement.get("session")) != str(matches[0].get("session"))):
                issues.append({"kind": "invalid_buy_signal_restate", "trade_index": i})
                continue
            entry = matches[0]
            replacement = copy.deepcopy(replacement)
            replacement.update(original_price=entry["price"], original_time=entry["time"],
                               adjustment_ids=[trade.get("id")], pnl_basis="committed_fill_plus_adjustments")
            entries[entries.index(entry)] = replacement
            continue
        if trade.get("adjustment_kind") == "buy_void":
            ref = trade.get("adjusts_entry_id")
            matches = [e for e in entries if ref and e.get("id") == ref
                       and e.get("side") == "buy" and e.get("code") == trade.get("code")
                       and e.get("qty") == trade.get("qty")]
            archived = any(t.get("id") == ref and t.get("reset_archived")
                           for t in state.get("trades", []))
            if len(matches) != 1 or not archived:
                issues.append({"kind": "invalid_buy_void", "trade_index": i})
                continue
            entry = matches[0]
            later = [e for e in entries if e.get("code") == entry.get("code")
                     and str(e.get("time", "")) > str(entry.get("time", ""))]
            if later or int(state["holdings"].get("positions", {}).get(entry["code"], {}).get("qty") or 0):
                issues.append({"kind": "buy_void_has_later_position", "trade_index": i})
                continue
            entries.remove(entry)
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


def closed_trade_rows(model, session, *, market_rows=()):
    """Independent full-exit cards from effective fills, including symbols bought again."""
    rows = []
    for entry in model.entries:
        if (entry.get("side") != "sell" or entry.get("after_qty") != 0
                or str(entry.get("session") or entry.get("time") or "")[:10] != session):
            continue
        qty = int(entry.get("qty") or 0)
        if qty <= 0:
            continue
        cost, pnl = number(entry.get("cost")), number(entry.get("pnl"))
        base = cost * qty + float(entry.get("allocated_buy_fees") or 0) if cost and cost > 0 else None
        at = entry.get("time")
        protection = number(entry.get("protection_price"))
        protection_source = "成交触发时保护线"
        # Older fills did not store the line. Reconstruct only while the retained
        # position watermark still belongs to this exact entry cycle.
        pos = model.state["holdings"].get("positions", {}).get(entry.get("code"), {})
        watermark = pos.get("quote_exit_watermark") or {}
        detail = str(entry.get("reason_detail") or entry.get("note") or entry.get("reason") or "")
        if (protection is None and "t1_peak_trail" in detail and cost and cost > 0
                and entry.get("buy_time") and watermark.get("cycle") == entry.get("buy_time")
                and str(watermark.get("time") or "") == str(entry.get("execution_quote_time") or entry.get("signal_time") or "")):
            from strategy.pullback_wave_stop import t1_trail_stop_px
            peak = number(pos.get("peak_high"))
            if peak and peak > 0:
                protection = t1_trail_stop_px(peak, cost_px=cost)
                protection_source = "按保留的成交时持仓峰值及当前规则复算"
        rows.append({"记录ID": entry.get("id"), "代码": entry.get("code"),
            "名称": entry.get("name") or entry.get("code"), "市场": entry.get("market"),
            "交易日": session, "持仓": 0, "可用": 0, "置顶": False, "槽位占用": False,
            "槽位留痕": True, "已实现": True, "三槽平仓": True, "持仓状态": "今日平仓",
            "卖出原因": "跌破隔夜峰值回落保护线" if "t1_peak_trail" in detail else detail,
            "回落止损价": protection, "回落止损价说明": protection_source if protection is not None else "触发时保护线未记录",
            "卖出数量": qty, "成本": cost, "成交价": entry.get("price"), "现价": None,
            "买入时间": entry.get("buy_time"), "平仓时间": at, "卖出时间": at,
            "信号时间": entry.get("signal_time") or at, "更新": at,
            "预警": "已平仓", "已触买": "否", "已触止损": "是",
            "当日盈亏": entry.get("day_pnl"), "当日盈亏%": entry.get("day_pnl_pct"),
            "浮盈": pnl, "浮盈%": entry.get("pnl_pct"), "盈亏状态": "结算",
            "盈亏说明": "今日卖出已结算；再次买入不覆盖本记录",
            "挂单说明": entry.get("note") or entry.get("reason"),
            "综合单笔收入": pnl, "综合单笔成本额": base,
            "综合单笔持仓数量": 0, "综合单笔卖出数量": qty,
            "综合单笔来源": "database_delivery_cycle_with_adjustments"})
    # Quotes may move after exit; committed fills and realized PnL stay frozen.
    fields = ("现价", "昨收", "开盘", "今日最高", "今日最低", "最高", "最低", "当日涨幅", "更新", "价位小数")
    quotes = {str(r.get("代码")): r for r in market_rows if number(r.get("现价")) is not None}
    for row in rows:
        source = quotes.get(str(row["代码"]), {})
        row.update({key: source[key] for key in fields if key in source})
    return sorted(rows, key=lambda row: (str(row.get("平仓时间") or ""), str(row.get("代码") or ""), str(row.get("记录ID") or "")))


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
    # A historical reconciliation warning does not invalidate today's committed
    # position marks and sale daily PnL. Corrections apply to the referenced fill's
    # session, even when the correction was recorded on a later day.
    def affects_session(issue):
        index = issue.get("trade_index")
        if not isinstance(index, int) or not 0 <= index < len(state.get("trades", [])):
            return True
        trade = state["trades"][index]
        ref = trade.get("adjusts_entry_id")
        targets = [e for e in entries if ref and e.get("id") == ref]
        if not targets:
            targets = [trade]
        days = [str(e.get("session") or e.get("time") or "")[:10] for e in targets]
        return any(not day or day == session for day in days)

    daily_ready = not any(affects_session(issue) for issue in issues)
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
    if model.issues:
        cycle_issues = [
            iss
            for iss in model.issues
            if "trade_index" in iss
            and iss["trade_index"] < len(state.get("trades", []))
            and state.get("trades", [])[iss["trade_index"]].get("code") == code
            and str(state.get("trades", [])[iss["trade_index"]].get("time") or "") >= str(buy.get("time") or "")
        ]
        if cycle_issues:
            return None
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
