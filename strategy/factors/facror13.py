from panda_backtest.api.api import *
import panda_data
import pandas as pd

# ------------------------------------------------------------
# 5日动量追涨杀跌(重构为开盘价±2.5%追涨杀跌)
# 买入: 动量因子选出 Top 10 中, 当日收盘/开盘-1 >= 2.5%(开盘价涨 2.5% 追买),
#       且前一日为阴线(收<开)或小阳线(收>开且涨幅<=1%),
#       且前两日累计涨幅 close[T-1]/close[T-3]-1 <= 5% -> 以 2.5% 仓位买入
#       且排除开盘/收盘涨停与一字涨停(买不进)
# 卖出: 持仓中某日收盘跌破开盘价-2.5%(收盘/开盘-1 <= -2.5%) -> 清仓离场
#       一字跌停封单则暂不卖出
# 持仓周期不固定, 每天逐股判断
# ------------------------------------------------------------

_LIMIT_PRICE_TOL = 0.01  # A 股最小价位 0.01


def initialize(context):
    context.account = "15032863"
    # 候选池与信号参数
    context.top_n = 10
    context.factor_direction = 1
    context.exclude_st = True
    context.exclude_limit_board = True   # 一字板/涨停不可买、一字跌停不可卖
    context.order_lot = 100
    context.position_pct = 0.025          # 单只买入仓位 2.5%
    context.entry_intraday_pct = 0.025    # 买入: 当日涨幅(收盘/开盘-1)>=2.5%
    context.small_yang_pct = 0.01         # 小阳线阈值: 前一日涨幅<=1%
    context.prior_2d_ret = 0.05           # 前两日累计涨幅<=5%
    context.exit_intraday_pct = 0.025     # 卖出: 收盘跌破开盘价-2.5%
    context.factor_by_date = {}
    context.series = {}                   # symbol -> {dates, open, close, high, low, limit_up, limit_down}
    init_market_data(context)


def _price_at_limit(price, limit_px, tol=_LIMIT_PRICE_TOL):
    """价位是否触及涨/跌停价(按 0.01 容差)。"""
    if price is None or limit_px is None:
        return False
    try:
        p = float(price)
        lim = float(limit_px)
    except (TypeError, ValueError):
        return False
    if p <= 0 or lim <= 0:
        return False
    return abs(p - lim) <= max(float(tol), 1e-8)


def _is_limit_up_unbuyable(open_t, high_t, low_t, close_t, limit_up):
    """开盘涨停 / 收盘涨停 / 全日一字涨停 → 买不进。"""
    if limit_up is None or float(limit_up or 0) <= 0:
        return False
    lim = float(limit_up)
    open_at = _price_at_limit(open_t, lim)
    close_at = _price_at_limit(close_t, lim)
    locked = (
        open_at
        and close_at
        and _price_at_limit(high_t, lim)
        and _price_at_limit(low_t, lim)
    )
    return bool(open_at or close_at or locked)


def _is_limit_down_unsellable(open_t, high_t, low_t, close_t, limit_down):
    """一字跌停(开高低收均锁跌停) → 卖不出。"""
    if limit_down is None or float(limit_down or 0) <= 0:
        return False
    lim = float(limit_down)
    return all(
        _price_at_limit(px, lim)
        for px in (open_t, high_t, low_t, close_t)
    )


def _load_market_df(start, end_date, include_st):
    """优先 get_stock_daily(含涨跌停); 失败则回退 get_market_data。"""
    fields_full = [
        "date", "symbol", "open", "close", "high", "low", "limit_up", "limit_down",
    ]
    try:
        df = panda_data.get_stock_daily(
            symbol=None,
            start_date=start,
            end_date=end_date,
            fields=fields_full,
            indicator="000300",
            st=bool(include_st),
        )
        if df is not None and not df.empty:
            return df, "get_stock_daily"
    except Exception as exc:
        print(f"[WARN] get_stock_daily 失败, 回退 get_market_data: {exc}")

    # 平台/旧接口回退: 可能无涨跌停字段
    try:
        df = panda_data.get_market_data(
            symbol=None,
            type="stock",
            start_date=start,
            end_date=end_date,
            fields=["date", "symbol", "open", "close", "high", "low"],
            indicator="000300",
        )
        if df is not None and not df.empty:
            return df, "get_market_data"
    except Exception as exc:
        print(f"[WARN] get_market_data 失败: {exc}")
    return None, None


def init_market_data(context):
    """一次性拉取历史行情并向量化计算 5 日动量因子, 同时缓存 OHLC + 涨跌停。"""
    start_date = "".join(ch for ch in str(context.run_info.start_date) if ch.isdigit())[:8]
    end_date = "".join(ch for ch in str(context.run_info.end_date) if ch.isdigit())[:8]
    lookback_days = 60
    start = (pd.to_datetime(start_date) - pd.Timedelta(days=lookback_days)).strftime("%Y%m%d")

    include_st = not bool(getattr(context, "exclude_st", True))
    df, src = _load_market_df(start, end_date, include_st=include_st)
    if df is None or df.empty:
        print(f"[WARN] init_market_data 行情为空 {start}~{end_date}")
        context.factor_by_date = {}
        context.series = {}
        return

    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    df["date"] = df["date"].astype(str).str.replace("-", "").str[:8]
    for col in ("high", "low", "limit_up", "limit_down"):
        if col not in df.columns:
            df[col] = float("nan")

    # 5 日动量: close/close(5日前)-1
    df["momentum"] = df.groupby("symbol")["close"].pct_change(5)
    df = df.dropna(subset=["momentum"])

    # 因子截面: dict[date] -> [(symbol, momentum, open, close)]
    factor_by_date = {}
    for _, row in df.iterrows():
        factor_by_date.setdefault(row["date"], []).append(
            (row["symbol"], float(row["momentum"]), float(row["open"]), float(row["close"]))
        )
    context.factor_by_date = factor_by_date

    def _f(x):
        try:
            v = float(x)
            return v if v == v else float("nan")  # NaN check
        except (TypeError, ValueError):
            return float("nan")

    series = {}
    for sym, g in df.groupby("symbol"):
        series[sym] = {
            "dates": list(g["date"]),
            "open": [_f(x) for x in g["open"]],
            "close": [_f(x) for x in g["close"]],
            "high": [_f(x) for x in g["high"]],
            "low": [_f(x) for x in g["low"]],
            "limit_up": [_f(x) for x in g["limit_up"]],
            "limit_down": [_f(x) for x in g["limit_down"]],
        }
    context.series = series
    has_limit = df["limit_up"].notna().any()
    print(
        f"[INFO] init_market_data 完成({src}): {len(factor_by_date)} 个交易日截面, "
        f"{len(series)} 只股票, limit_up可用={bool(has_limit)}"
    )


def _top_candidates(context, today):
    """返回今日动量因子 Top-N 的 symbol 列表。"""
    rows = context.factor_by_date.get(today)
    if not rows:
        return []
    if context.exclude_st:
        rows = [r for r in rows if "ST" not in r[0]]
    rows.sort(key=lambda r: r[1], reverse=(context.factor_direction == 1))
    return [r[0] for r in rows[: max(1, int(context.top_n))]]


def _bar(context, sym, today):
    ser = context.series.get(sym)
    if not ser:
        return None
    if today not in ser["dates"]:
        return None
    idx = ser["dates"].index(today)
    return idx, ser


def _ohlc_limit(ser, idx):
    open_t = ser["open"][idx]
    close_t = ser["close"][idx]
    high_t = ser.get("high", ser["close"])[idx]
    low_t = ser.get("low", ser["open"])[idx]
    limit_up = ser.get("limit_up", [float("nan")] * len(ser["dates"]))[idx]
    limit_down = ser.get("limit_down", [float("nan")] * len(ser["dates"]))[idx]
    return open_t, high_t, low_t, close_t, limit_up, limit_down


def _check_entry(context, sym, today):
    """买入条件: 当日涨幅>=2.5%, 前一日阴线或小阳线, 前两日累计涨幅<=5%, 非涨停/一字板。"""
    res = _bar(context, sym, today)
    if not res:
        return False
    idx, ser = res
    if idx < 3:
        return False
    open_t, high_t, low_t, close_t, limit_up, _ = _ohlc_limit(ser, idx)
    open_p, close_p = ser["open"][idx - 1], ser["close"][idx - 1]
    close_p3 = ser["close"][idx - 3]
    if open_t <= 0:
        return False
    # 一字涨停开盘 / 收盘涨停 / 全日一字 → 买不进
    if getattr(context, "exclude_limit_board", True):
        if _is_limit_up_unbuyable(open_t, high_t, low_t, close_t, limit_up):
            return False
    # 当日涨幅基于开盘价 >= 2.5%
    if close_t / open_t - 1 < context.entry_intraday_pct:
        return False
    # 前一日: 阴线(close<open) 或 小阳线(close>open 且涨幅<=阈值)
    if close_p > open_p:
        if open_p <= 0:
            return False
        if close_p / open_p - 1 > context.small_yang_pct:
            return False
    # 前两日累计涨幅 <= 5%
    if close_p3 > 0 and close_p / close_p3 - 1 > context.prior_2d_ret:
        return False
    return True


def _check_exit(context, sym, today):
    """卖出: 当日收盘跌破开盘价-2.5%; 一字跌停则暂不卖。"""
    res = _bar(context, sym, today)
    if not res:
        return False
    idx, ser = res
    open_t, high_t, low_t, close_t, _, limit_down = _ohlc_limit(ser, idx)
    if open_t <= 0:
        return False
    if close_t / open_t - 1 > -context.exit_intraday_pct:
        return False
    # 一字跌停封单卖不出
    if getattr(context, "exclude_limit_board", True):
        if _is_limit_down_unsellable(open_t, high_t, low_t, close_t, limit_down):
            return False
    return True


def handle_data(context, data):
    today = context.now[:8] if isinstance(context.now, str) else context.now.strftime("%Y%m%d")
    stock_account = context.stock_account_dict.get(context.account)
    if stock_account is None:
        print(f"[{today}] 股票账户不存在")
        return
    total_value = float(stock_account.total_value)
    if total_value <= 0:
        return
    positions = dict(stock_account.positions)

    # 第一步: 卖出检查(持仓周期不固定, 每天判断, 跌破开盘价-2.5%即清仓)
    for sym, pos in positions.items():
        held = int(getattr(pos, "quantity", 0) or 0)
        if held <= 0:
            continue
        if _check_exit(context, sym, today):
            sellable = int(getattr(pos, "sellable", held) or held)
            if sellable > 0:
                order_shares(context.account, sym, -sellable, style=MarketOrderStyle, remark="跌破开盘价卖出")

    # 第二步: 买入检查(动量 Top 中满足追涨条件)
    cands = _top_candidates(context, today)
    if not cands:
        return
    cash = float(stock_account.cash)
    lot = max(1, int(getattr(context, "order_lot", 100) or 100))
    for sym in cands:
        if cash <= 0:
            break
        pos_now = positions.get(sym)
        held_now = int(getattr(pos_now, "quantity", 0) or 0)
        if held_now > 0:
            continue  # 已有持仓不加仓
        if not _check_entry(context, sym, today):
            continue
        bar = data[sym]
        if bar is None:
            continue
        close_val = getattr(bar, "close", None)
        if close_val is None or float(close_val) <= 0:
            continue
        price = float(close_val)
        target_val = total_value * context.position_pct
        buy_value = min(target_val, cash)
        qty = int(buy_value // price // lot) * lot
        if qty <= 0:
            continue
        order_shares(context.account, sym, qty, style=MarketOrderStyle, remark="开盘价追涨买入")
        cash -= qty * price
