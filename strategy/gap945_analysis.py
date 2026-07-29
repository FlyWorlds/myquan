"""低开 945 规则：统计与收益对比分析。"""

from __future__ import annotations

from dataclasses import replace
import pandas as pd

from strategy.backtest import metric
from strategy.config import BacktestConfig
from strategy.open_break import (
    TICK_SIZE,
    bar_close_at_time,
    entry_trigger_price,
    gap_down_flipped_red,
    gap945_exit_close,
    has_double_yang_before,
    is_yin,
    morning_high_before_gap945,
    prev_day_allows_entry,
    stop_trigger_price,
)
from strategy.runner import run_open_break_backtest

CERTAIN_CATS = frozenset({"exact_945前未翻红", "推断_945前未翻红(日高<昨收)"})


def classify_gap_days(daily: pd.DataFrame, minute: pd.DataFrame) -> pd.DataFrame:
    by_day: dict[str, pd.DataFrame] = {}
    if minute is not None and not minute.empty:
        m = minute.copy()
        m["day"] = m["ts"].dt.strftime("%Y-%m-%d")
        for d, grp in m.groupby("day"):
            by_day[str(d)] = grp.sort_values("ts")

    ts = pd.to_datetime(daily["date"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("Asia/Shanghai")
    df = daily.copy()
    df["day"] = ts.dt.strftime("%Y-%m-%d")
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col])

    rows: list[dict] = []
    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        day = str(row["day"])
        prev_close = float(prev["close"])
        o = float(row["open"])
        h = float(row["high"])
        if prev_close <= 0 or o <= 0 or o + 1e-12 >= prev_close:
            continue

        day_min = by_day.get(day)
        has_1m = day_min is not None and not day_min.empty
        if has_1m:
            day0 = day_min["ts"].dt.normalize().iloc[0]
            mh = morning_high_before_gap945(day_min, open_px=o, day0=day0)
            flipped = gap_down_flipped_red(mh, prev_close)
            exit945 = gap945_exit_close(day_min, day0=day0)
            if flipped:
                cat = "exact_945前已翻红"
            elif exit945 is not None:
                cat = "exact_945前未翻红"
            else:
                cat = "exact_无945K线"
        elif h + 1e-12 < prev_close:
            cat = "推断_945前未翻红(日高<昨收)"
            mh = h
        else:
            cat = "不确定_日高≥昨收(或945后翻红)"
            mh = h

        rows.append(
            {
                "day": day,
                "open": o,
                "prev_close": prev_close,
                "high": h,
                "close": float(row["close"]),
                "gap_pct": (o / prev_close - 1) * 100,
                "category": cat,
                "has_1m": has_1m,
                "morning_high": mh,
            }
        )
    return pd.DataFrame(rows)


def replay_holding_days(
    daily: pd.DataFrame,
    *,
    threshold_pct: float,
    tick: float = TICK_SIZE,
) -> pd.DataFrame:
    """简化重放：统计 T+1 可卖持仓日（不含 945，供分析用）。"""
    ts = pd.to_datetime(daily["date"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("Asia/Shanghai")
    df = daily.copy()
    df["day"] = ts.dt.strftime("%Y-%m-%d")
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col])

    armed = True
    entry_price = None
    buy_day = None
    pos = 0.0
    prev_open = prev_close = prev2_open = prev2_close = None
    holding_days: list[dict] = []

    for i in range(len(df)):
        row = df.iloc[i]
        day = str(row["day"])
        o = float(row["open"])
        h = float(row["high"])
        low = float(row["low"])
        c = float(row["close"])

        entry_px = entry_trigger_price(o, entry_pct=threshold_pct, tick=tick)
        stop_px = stop_trigger_price(o, stop_pct=threshold_pct, tick=tick)
        hit_entry = h + 1e-12 >= entry_px
        hit_stop = low <= stop_px + 1e-12
        yin = is_yin(o, c)
        bought_today = False

        if (
            armed
            and pos <= 0
            and hit_entry
            and prev_open is not None
            and prev_close is not None
            and prev_day_allows_entry(
                prev_open, prev_close, prev_small_yang_pct=threshold_pct
            )
            and not has_double_yang_before(
                prev2_open, prev2_close, prev_open, prev_close
            )
        ):
            pos = 1.0
            armed = False
            entry_price = entry_px
            buy_day = day
            bought_today = True

        if pos > 0 and buy_day != day:
            holding_days.append(
                {
                    "day": day,
                    "buy_day": buy_day,
                    "entry": entry_price,
                    "prev_close": float(df.iloc[i - 1]["close"]) if i > 0 else None,
                    "open": o,
                    "high": h,
                    "close": c,
                }
            )

        if pos > 0 and not bought_today and buy_day != day and (hit_stop or yin):
            pos = 0.0
            armed = True
            entry_price = None
            buy_day = None

        prev2_open, prev2_close = prev_open, prev_close
        prev_open, prev_close = o, c

    return pd.DataFrame(holding_days)


def exit_without_gap945(
    open_px: float,
    low: float,
    close: float,
    *,
    stop_pct: float,
    tick: float = TICK_SIZE,
) -> tuple[float, str]:
    """不执行 945 时当日卖出价：止损 > 阴线 > 持有至收盘。"""
    stop_px = stop_trigger_price(open_px, stop_pct=stop_pct, tick=tick)
    if low <= stop_px + 1e-12:
        return float(stop_px), "止损"
    if is_yin(open_px, close):
        return float(close), "阴线收盘"
    return float(close), "阳/十字持有(按收盘计)"


def per_event_compare(
    daily: pd.DataFrame,
    gap_map: dict,
    hold_df: pd.DataFrame,
    gap_df: pd.DataFrame,
    *,
    threshold_pct: float,
) -> pd.DataFrame:
    ts = pd.to_datetime(daily["date"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("Asia/Shanghai")
    px = daily.copy()
    px["day"] = ts.dt.strftime("%Y-%m-%d")
    for col in ("open", "high", "low", "close"):
        px[col] = pd.to_numeric(px[col])
    px_by_day = px.set_index("day")

    events = gap_df[gap_df["holding"] & gap_df["category"].isin(CERTAIN_CATS)].copy()
    rows: list[dict] = []
    for _, ev in events.iterrows():
        day = str(ev["day"])
        if day not in px_by_day.index:
            continue
        bar = px_by_day.loc[day]
        hold = hold_df[hold_df["day"] == day].iloc[0]
        entry = float(hold["entry"])
        o = float(bar["open"])
        low = float(bar["low"])
        c = float(bar["close"])

        g = gap_map.get(day)
        exit945 = float(g["exit_px"]) if g else o
        src = str(g.get("source") if g else "fallback_open")

        no945_px, no945_reason = exit_without_gap945(
            o, low, c, stop_pct=threshold_pct
        )
        pnl945 = (exit945 / entry - 1) * 100
        pnl_no945 = (no945_px / entry - 1) * 100
        diff = pnl945 - pnl_no945

        rows.append(
            {
                "day": day,
                "buy_day": hold["buy_day"],
                "entry": entry,
                "open": o,
                "high": float(bar["high"]),
                "close": c,
                "exit945": exit945,
                "exit945_src": src,
                "no945_px": no945_px,
                "no945_reason": no945_reason,
                "pnl945_pct": pnl945,
                "pnl_no945_pct": pnl_no945,
                "diff_pct": diff,
                "better": "945卖" if diff > 0 else ("不卖" if diff < 0 else "持平"),
            }
        )
    return pd.DataFrame(rows)


def yearly_equity_diff(
    res_on: aq.BacktestResult,
    res_off: aq.BacktestResult,
    *,
    initial_cash: float,
) -> pd.DataFrame:
    eq_on = res_on.equity_curve_daily
    eq_off = res_off.equity_curve_daily
    if isinstance(eq_on, pd.DataFrame):
        eq_on = eq_on.iloc[:, 0]
    if isinstance(eq_off, pd.DataFrame):
        eq_off = eq_off.iloc[:, 0]
    eq_on = eq_on.copy().sort_index()
    eq_off = eq_off.copy().sort_index()
    if eq_on.index.tz is not None:
        eq_on.index = eq_on.index.tz_convert("Asia/Shanghai")
    if eq_off.index.tz is not None:
        eq_off.index = eq_off.index.tz_convert("Asia/Shanghai")

    years = sorted(set(eq_on.index.year) | set(eq_off.index.year))
    rows: list[dict] = []
    prev_on = prev_off = initial_cash
    for y in years:
        y_on = eq_on[eq_on.index.year == y]
        y_off = eq_off[eq_off.index.year == y]
        if y_on.empty or y_off.empty:
            continue
        end_on = float(y_on.iloc[-1])
        end_off = float(y_off.iloc[-1])
        rows.append(
            {
                "year": y,
                "end_945_on": end_on,
                "end_945_off": end_off,
                "diff_yuan": end_on - end_off,
                "ret_945_on_pct": (end_on / prev_on - 1) * 100 if prev_on > 0 else float("nan"),
                "ret_945_off_pct": (end_off / prev_off - 1) * 100 if prev_off > 0 else float("nan"),
                "diff_ret_pp": (
                    (end_on / prev_on - 1) - (end_off / prev_off - 1)
                )
                * 100
                if prev_on > 0 and prev_off > 0
                else float("nan"),
            }
        )
        prev_on, prev_off = end_on, end_off
    return pd.DataFrame(rows)


def compare_gap945_on_off(
    cfg: BacktestConfig,
    daily: pd.DataFrame,
    gap_map: dict,
) -> tuple[aq.BacktestResult, aq.BacktestResult]:
    return (
        run_open_break_backtest(replace(cfg, enable_gap945=True), daily, gap_map=gap_map),
        run_open_break_backtest(replace(cfg, enable_gap945=False), daily, gap_map=gap_map),
    )


def format_metric(result: aq.BacktestResult, name: str) -> float:
    return metric(result.metrics_df, name)
