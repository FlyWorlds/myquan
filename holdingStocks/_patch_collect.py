from pathlib import Path

p = Path(__file__).with_name("index.py")
text = p.read_text(encoding="utf-8")
start = text.index("def collect_rows()")
end = text.index("def _fmt_num")
new = '''def collect_rows() -> list[dict[str, Any]]:
    """拉取行情并合并持仓；已触止损视为成交并锁定当日收益。"""
    holdings = load_holdings()
    positions = holdings.get("positions", {})
    realized_map = holdings.get("realized_today", {})
    rows: list[dict[str, Any]] = []
    session_today: str | None = None

    for w in WATCHLIST:
        code = w["code"]
        entry_pct = _watch_pct(w)
        stop_pct = entry_pct
        tick = _watch_tick(w)
        px_digits = _px_digits(tick)
        pct_pct = round(entry_pct * 100.0, 2)
        try:
            q = fetch_today_quote(w["sina"])
            session_today = q["session"]
            lv = strategy_levels(
                q["open"], entry_pct=entry_pct, stop_pct=stop_pct, tick=tick
            )
            vs = points_vs_open(q["open"], q["last"])
            day_chg = q.get("day_chg_pct")
            hit_buy = q["high"] + 1e-12 >= lv["buy_trigger"]
            hit_stop = q["low"] <= lv["stop"] + 1e-12
            pos = positions.get(code, {})
            qty = int(pos.get("qty") or 0)
            buy_time = pos.get("buy_time")
            cost = pos.get("cost")
            t0 = bool(w.get("t0"))
            t1_lock = qty > 0 and (not t0) and _is_t1_buy_day(buy_time, q["session"])

            # 已触止损且可卖 → 视为成交，锁定收益并清仓
            if qty > 0 and hit_stop and not t1_lock:
                apply_stop_fill(
                    code=code,
                    meta=w,
                    stop_px=float(lv["stop"]),
                    qty=qty,
                    cost=float(cost) if cost is not None else None,
                    session=q["session"],
                    buy_time=buy_time,
                    prev_close=q.get("prev_close"),
                    open_px=float(q["open"]),
                    px_digits=px_digits,
                )
                holdings = load_holdings()
                positions = holdings.get("positions", {})
                realized_map = holdings.get("realized_today", {})
                pos = positions.get(code, {})
                qty = int(pos.get("qty") or 0)
                cost = pos.get("cost")
                buy_time = pos.get("buy_time")

            # 当日已止损成交：收益冻结，不再跟现价
            realized = realized_map.get(code)
            if (
                realized
                and str(realized.get("session") or "") == q["session"]
                and realized.get("reason") == "止损成交"
            ):
                fill_px = float(realized["price"])
                sold_qty = int(realized.get("qty") or 0)
                rows.append(
                    {
                        "市场": w["market"],
                        "代码": code,
                        "名称": w["name"],
                        "交易日": q["session"],
                        "开盘": round(q["open"], px_digits),
                        "最高": round(q["high"], px_digits),
                        "最低": round(q["low"], px_digits),
                        "现价": round(fill_px, px_digits),
                        "昨收": None
                        if q.get("prev_close") is None
                        else round(float(q["prev_close"]), px_digits),
                        "当日涨幅": None if day_chg is None else round(float(day_chg), 2),
                        "较开盘点": round(points_vs_open(q["open"], fill_px), 2),
                        "阈值%": pct_pct,
                        "买点": lv["buy_trigger"],
                        "止损": lv["stop"],
                        "已触买": "是" if hit_buy else "否",
                        "已触止损": "是",
                        "形态": bar_shape(q["open"], fill_px),
                        "预警": "止损成交",
                        "建议挂单": None,
                        "挂单说明": f"已按止损价成交@{fill_px:.{px_digits}f}，收益已锁定",
                        "近买点": False,
                        "近止损": False,
                        "bg_class": "warn-sell",
                        "持仓": 0,
                        "卖出数量": sold_qty,
                        "成本": realized.get("cost"),
                        "浮盈": realized.get("pnl"),
                        "浮盈%": realized.get("pnl_pct"),
                        "当日盈亏": realized.get("day_pnl"),
                        "当日盈亏%": realized.get("day_pnl_pct"),
                        "市值": 0.0,
                        "成本额": None,
                        "已实现": True,
                        "价位小数": px_digits,
                        "更新": q["last_ts"][11:19]
                        if len(q["last_ts"]) >= 19
                        else q["last_ts"],
                        "error": None,
                    }
                )
                continue

            sig = strategy_signal(
                open_px=q["open"],
                high_px=q["high"],
                low_px=q["low"],
                last_px=q["last"],
                session=q["session"],
                buy_trigger=lv["buy_trigger"],
                stop_px=lv["stop"],
                qty=qty,
                buy_time=buy_time,
                vs_open_pts=vs,
                entry_pct=entry_pct,
                stop_pct=stop_pct,
                px_digits=px_digits,
                t0=t0,
            )
            pnl = None
            pnl_pct = None
            market_value = (q["last"] * qty) if qty > 0 else None
            cost_value = None
            day_pnl = None
            day_pnl_pct = None
            if cost is not None:
                cost_f = float(cost)
                pnl_pct = (q["last"] / cost_f - 1.0) * 100.0
                if qty > 0:
                    pnl = (q["last"] - cost_f) * qty
                    cost_value = cost_f * qty
                else:
                    pnl = q["last"] - cost_f

            if qty > 0:
                bought_today = _is_t1_buy_day(buy_time, q["session"])
                if bought_today:
                    base_px = float(cost) if cost is not None else float(q["open"])
                    day_pnl = (q["last"] - base_px) * qty
                    day_pnl_pct = (
                        (q["last"] / base_px - 1.0) * 100.0 if base_px > 0 else None
                    )
                elif q.get("prev_close") is not None and float(q["prev_close"]) > 0:
                    base_px = float(q["prev_close"])
                    day_pnl = (q["last"] - base_px) * qty
                    day_pnl_pct = (q["last"] / base_px - 1.0) * 100.0

            rows.append(
                {
                    "市场": w["market"],
                    "代码": code,
                    "名称": w["name"],
                    "交易日": q["session"],
                    "开盘": round(q["open"], px_digits),
                    "最高": round(q["high"], px_digits),
                    "最低": round(q["low"], px_digits),
                    "现价": round(q["last"], px_digits),
                    "昨收": None
                    if q.get("prev_close") is None
                    else round(float(q["prev_close"]), px_digits),
                    "当日涨幅": None if day_chg is None else round(float(day_chg), 2),
                    "较开盘点": round(vs, 2),
                    "阈值%": pct_pct,
                    "买点": lv["buy_trigger"],
                    "止损": lv["stop"],
                    "已触买": "是" if hit_buy else "否",
                    "已触止损": "是" if hit_stop else "否",
                    "形态": sig["形态"],
                    "预警": sig["alert"],
                    "建议挂单": sig["建议挂单"],
                    "挂单说明": sig["挂单说明"],
                    "近买点": sig["pending_buy"],
                    "近止损": sig["pending_sell"],
                    "bg_class": sig["bg_class"],
                    "持仓": qty,
                    "成本": None if cost is None else float(cost),
                    "浮盈": None if pnl is None else round(float(pnl), 2),
                    "浮盈%": None if pnl_pct is None else round(float(pnl_pct), 2),
                    "当日盈亏": None if day_pnl is None else round(float(day_pnl), 2),
                    "当日盈亏%": None
                    if day_pnl_pct is None
                    else round(float(day_pnl_pct), 2),
                    "市值": None if market_value is None else round(float(market_value), 2),
                    "成本额": None if cost_value is None else round(float(cost_value), 2),
                    "已实现": False,
                    "价位小数": px_digits,
                    "更新": q["last_ts"][11:19]
                    if len(q["last_ts"]) >= 19
                    else q["last_ts"],
                    "error": None,
                }
            )
        except Exception as e:  # noqa: BLE001
            pos = positions.get(code, {})
            rows.append(
                {
                    "市场": w["market"],
                    "代码": code,
                    "名称": w["name"],
                    "交易日": "-",
                    "开盘": None,
                    "最高": None,
                    "最低": None,
                    "现价": None,
                    "当日涨幅": None,
                    "较开盘点": None,
                    "阈值%": pct_pct,
                    "买点": None,
                    "止损": None,
                    "已触买": "-",
                    "已触止损": "-",
                    "形态": "-",
                    "预警": "",
                    "建议挂单": None,
                    "挂单说明": "",
                    "近买点": False,
                    "近止损": False,
                    "bg_class": "",
                    "持仓": int(pos.get("qty") or 0),
                    "成本": pos.get("cost"),
                    "浮盈": None,
                    "浮盈%": None,
                    "昨收": None,
                    "当日盈亏": None,
                    "当日盈亏%": None,
                    "市值": None,
                    "成本额": None,
                    "已实现": False,
                    "价位小数": px_digits,
                    "更新": "-",
                    "error": str(e),
                }
            )

    if session_today:
        data = load_holdings()
        before = dict(data.get("realized_today") or {})
        _purge_stale_realized(data, session_today)
        if data.get("realized_today") != before:
            save_holdings(data)

    total_mv = sum(
        float(r["市值"])
        for r in rows
        if r.get("市值") is not None and int(r.get("持仓") or 0) > 0
    )
    for r in rows:
        qty = int(r.get("持仓") or 0)
        mv = r.get("市值")
        if qty > 0 and mv is not None and total_mv > 0:
            r["仓位%"] = round(float(mv) / total_mv * 100.0, 1)
        else:
            r["仓位%"] = 0.0 if r.get("已实现") else None
    return rows


'''
p.write_text(text[:start] + new + text[end:], encoding="utf-8")
print("ok", start, end)
