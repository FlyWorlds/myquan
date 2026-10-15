"""Read-only boot inventory preview. Unknown quotes never become executable signals."""
from __future__ import annotations

from datetime import datetime

from account_reconciliation import account_summary, number


def build_boot_holdings(model, *, session, clock, get_quote=None):
    from strategy.akq_math import session_day_pnl
    from watch_config import sina_of
    rows = []
    for code, pos in model.state["holdings"].get("positions", {}).items():
        qty = int(pos.get("qty") or 0)
        if qty <= 0:
            continue
        row = {"代码": code, "名称": pos.get("name") or code, "市场": pos.get("market"),
               "持仓": qty, "可用": pos.get("available"), "成本": pos.get("cost"),
               "买入时间": pos.get("buy_time"), "置顶": True, "已实现": False,
               "持仓状态": "已经买入", "交易日": session, "现价": None,
               "当日盈亏": None, "浮盈": None, "市值": None,
               "买点": None, "止损": None, "已触买": "否", "已触止损": "否",
               "持仓最高": pos.get("peak_high"), "预警": "", "bgClass": "status-hold"}
        try:
            q = get_quote(sina_of(code)) if get_quote else None
        except Exception:
            q = None
        if q and str(q.get("session") or "")[:10] == session and "daily" not in str(q.get("_quote_source") or ""):
            try:
                at = datetime.fromisoformat(str(q.get("last_ts") or ""))
                valid = at.tzinfo is None and at.date().isoformat() == session and at <= datetime.fromisoformat(clock)
            except ValueError:
                valid = False
            mark, cost = number(q.get("last")), number(pos.get("cost"))
            if valid and mark is not None and mark > 0:
                row.update({"现价": mark, "昨收": number(q.get("prev_close")),
                            "开盘": number(q.get("open")), "今日最高": number(q.get("high")),
                            "当日涨幅": number(q.get("day_chg_pct")), "更新": q.get("last_ts"),
                            "市值": round(mark * qty, 2)})
                if cost is not None and cost > 0:
                    day, pct, _ = session_day_pnl(mark=mark, qty=qty, cost=cost,
                            prev_close=row.get("昨收"), bought_today=str(pos.get("buy_time") or "")[:10] == session,
                            fallback=None)
                    row.update({"浮盈": round((mark-cost)*qty, 2), "浮盈%": round((mark/cost-1)*100, 2),
                                "当日盈亏": day, "当日盈亏%": pct})
        rows.append(row)
    return rows, account_summary(model.state, rows, session, read_model=model)
