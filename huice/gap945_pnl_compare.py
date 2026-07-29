"""对比持有时「945 全清」vs「不执行 945 规则」的收益。"""

from __future__ import annotations

import datetime as dt
import logging
import sys
from pathlib import Path

import akquant as aq
import pandas as pd
from akquant import CurrentClose

_MYQUAN_ROOT = Path(__file__).resolve().parents[1]
if str(_MYQUAN_ROOT) not in sys.path:
    sys.path.insert(0, str(_MYQUAN_ROOT))

from gap945_hold_stats import classify_gap_days, replay_holding_days
from strategy import (
    OpenBreak3Strategy,
    build_gap_down_945_proxy_map,
    fetch_daily,
    fetch_minute_1m,
    is_yin,
)
from strategy.backtest import _metric
from strategy.open_break import TICK_SIZE, stop_trigger_price

SYMBOL = "sh600552"
EM_SYMBOL = "600552"
SYMBOL_NAME = "凯盛科技"
START_DATE = "20200101"
END_DATE = dt.date.today().strftime("%Y%m%d")
THRESHOLD_PCT = 0.025
INITIAL_CASH = 100_000.0
TARGET_PCT = 0.95
LOT_SIZE = 100
COMMISSION_RATE = 0.0000854
STAMP_TAX_RATE = 0.001
SLIPPAGE = {"type": "percent", "value": 0.001}
FILL_CLOSE = CurrentClose()
MIN1_CACHE = Path(__file__).with_name(f"{SYMBOL}_1m_qfq.parquet")

CERTAIN_CATS = {"exact_945前未翻红", "推断_945前未翻红(日高<昨收)"}


def run_backtest(daily: pd.DataFrame, gap_map: dict, *, enable_gap945: bool) -> aq.BacktestResult:
    OpenBreak3Strategy.symbol = SYMBOL
    OpenBreak3Strategy.symbol_name = SYMBOL_NAME
    OpenBreak3Strategy.target_pct = TARGET_PCT
    OpenBreak3Strategy.lot_size = LOT_SIZE
    OpenBreak3Strategy.start_date = START_DATE
    OpenBreak3Strategy.end_date = END_DATE
    OpenBreak3Strategy.slippage_value = SLIPPAGE["value"]
    OpenBreak3Strategy.gap_down_945_map = gap_map
    OpenBreak3Strategy.enable_gap945 = enable_gap945
    OpenBreak3Strategy.entry_pct = THRESHOLD_PCT
    OpenBreak3Strategy.stop_pct = THRESHOLD_PCT
    OpenBreak3Strategy.prev_small_yang_pct = THRESHOLD_PCT

    return aq.run_backtest(
        data=daily,
        strategy=OpenBreak3Strategy,
        symbols=SYMBOL,
        initial_cash=INITIAL_CASH,
        commission_rate=COMMISSION_RATE,
        stamp_tax_rate=STAMP_TAX_RATE,
        t_plus_one=True,
        lot_size=LOT_SIZE,
        fill_policy=FILL_CLOSE,
        slippage=SLIPPAGE,
        timezone="Asia/Shanghai",
        show_progress=False,
    )


def no945_exit_px(o: float, low: float, c: float, stop_pct: float) -> tuple[float, str]:
    """不执行 945 规则时，当日策略卖出价（优先级：止损 > 阴线收盘 > 持有至收盘）。"""
    stop_px = stop_trigger_price(o, stop_pct=stop_pct, tick=TICK_SIZE)
    if low <= stop_px + 1e-12:
        return float(stop_px), "止损"
    if is_yin(o, c):
        return float(c), "阴线收盘"
    return float(c), "阳/十字持有(按收盘计)"


def per_event_compare(
    daily: pd.DataFrame,
    gap_map: dict,
    hold_df: pd.DataFrame,
    gap_df: pd.DataFrame,
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
        o, h, low, c = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"])

        g = gap_map.get(day)
        exit945 = float(g["exit_px"]) if g else float(o)
        src = str(g.get("source") if g else "fallback_open")

        no945_px, no945_reason = no945_exit_px(o, low, c, THRESHOLD_PCT)
        pnl945 = (exit945 / entry - 1) * 100
        pnl_no945 = (no945_px / entry - 1) * 100
        pnl_close = (c / entry - 1) * 100
        diff = pnl945 - pnl_no945

        rows.append(
            {
                "day": day,
                "buy_day": hold["buy_day"],
                "entry": entry,
                "open": o,
                "high": h,
                "close": c,
                "exit945": exit945,
                "exit945_src": src,
                "no945_px": no945_px,
                "no945_reason": no945_reason,
                "pnl945_pct": pnl945,
                "pnl_no945_pct": pnl_no945,
                "pnl_close_pct": pnl_close,
                "diff_pct": diff,
                "better": "945卖" if diff > 0 else ("不卖" if diff < 0 else "持平"),
            }
        )
    return pd.DataFrame(rows)


def yearly_equity_diff(res_sell: aq.BacktestResult, res_hold: aq.BacktestResult) -> pd.DataFrame:
    eq_s = res_sell.equity_curve_daily
    eq_h = res_hold.equity_curve_daily
    if isinstance(eq_s, pd.DataFrame):
        eq_s = eq_s.iloc[:, 0]
    if isinstance(eq_h, pd.DataFrame):
        eq_h = eq_h.iloc[:, 0]
    eq_s = eq_s.copy()
    eq_h = eq_h.copy()
    if eq_s.index.tz is not None:
        eq_s.index = eq_s.index.tz_convert("Asia/Shanghai")
    if eq_h.index.tz is not None:
        eq_h.index = eq_h.index.tz_convert("Asia/Shanghai")
    eq_s = eq_s.sort_index()
    eq_h = eq_h.sort_index()

    years = sorted(set(eq_s.index.year) | set(eq_h.index.year))
    rows: list[dict] = []
    prev_s = prev_h = INITIAL_CASH
    for y in years:
        s_y = eq_s[eq_s.index.year == y]
        h_y = eq_h[eq_h.index.year == y]
        if s_y.empty or h_y.empty:
            continue
        end_s = float(s_y.iloc[-1])
        end_h = float(h_y.iloc[-1])
        ret_s = (end_s / prev_s - 1) * 100 if prev_s > 0 else float("nan")
        ret_h = (end_h / prev_h - 1) * 100 if prev_h > 0 else float("nan")
        rows.append(
            {
                "year": y,
                "end_945_on": end_s,
                "end_945_off": end_h,
                "diff_yuan": end_s - end_h,
                "ret_945_on_pct": ret_s,
                "ret_945_off_pct": ret_h,
                "diff_ret_pp": ret_s - ret_h,
            }
        )
        prev_s, prev_h = end_s, end_h
    return pd.DataFrame(rows)


def main() -> None:
    logging.getLogger("akquant").setLevel(logging.WARNING)
    logging.getLogger("akquant.strategy").setLevel(logging.WARNING)
    logging.getLogger("akquant.backtest").setLevel(logging.WARNING)
    daily = fetch_daily(SYMBOL, START_DATE, END_DATE)
    minute = fetch_minute_1m(
        sina_symbol=SYMBOL,
        em_symbol=EM_SYMBOL,
        cache_path=MIN1_CACHE,
        start_date=START_DATE,
        end_date=END_DATE,
    )
    gap_map = build_gap_down_945_proxy_map(daily, minute, proxy="open")
    gap_df = classify_gap_days(daily, minute)
    hold_df = replay_holding_days(daily)
    hold_set = set(hold_df["day"])
    gap_df["holding"] = gap_df["day"].isin(hold_set)

    res_sell = run_backtest(daily, gap_map, enable_gap945=True)
    res_hold = run_backtest(daily, gap_map, enable_gap945=False)

    ev = per_event_compare(daily, gap_map, hold_df, gap_df)
    n = len(ev)
    sell_wins = int((ev["diff_pct"] > 0).sum()) if n else 0
    hold_wins = int((ev["diff_pct"] < 0).sum()) if n else 0
    tie = n - sell_wins - hold_wins

    print(f"=== {SYMBOL_NAME} 945全清 vs 不卖 收益对比 ===")
    print(f"区间: {START_DATE} ~ {END_DATE}")
    print()
    print("【全区间回测】（945 卖价：有 1m 用精确价，否则用开盘价 proxy）")
    print(f"  945规则开启: 累计 { _metric(res_sell.metrics_df, 'total_return_pct'):.2f}%  "
          f"期末 {_metric(res_sell.metrics_df, 'end_market_value'):,.0f}  "
          f"回撤 {_metric(res_sell.metrics_df, 'max_drawdown_pct'):.2f}%")
    print(f"  945规则关闭: 累计 {_metric(res_hold.metrics_df, 'total_return_pct'):.2f}%  "
          f"期末 {_metric(res_hold.metrics_df, 'end_market_value'):,.0f}  "
          f"回撤 {_metric(res_hold.metrics_df, 'max_drawdown_pct'):.2f}%")
    diff_eq = _metric(res_sell.metrics_df, "end_market_value") - _metric(
        res_hold.metrics_df, "end_market_value"
    )
    diff_ret = _metric(res_sell.metrics_df, "total_return_pct") - _metric(
        res_hold.metrics_df, "total_return_pct"
    )
    print(f"  差额(945开-945关): {diff_ret:+.2f} pp，期末 {diff_eq:+,.0f} 元")
    print(f"  945开启多赚: {diff_eq/INITIAL_CASH*100:.2f}%（相对初始本金）")
    print(f"  945 proxy 触发日历日: {len(gap_map)}（持有时确定945前未翻红事件: {n}）")
    print()
    ydiff = yearly_equity_diff(res_sell, res_hold)
    if not ydiff.empty:
        print("【分年权益差价】")
        print(
            f"  {'年份':>4}  {'945开权益':>12}  {'945关权益':>12}  "
            f"{'差价(元)':>12}  {'945开收益%':>10}  {'945关收益%':>10}  {'收益差pp':>8}"
        )
        for _, r in ydiff.iterrows():
            print(
                f"  {int(r['year']):>4}  {r['end_945_on']:>12,.0f}  {r['end_945_off']:>12,.0f}  "
                f"{r['diff_yuan']:>+12,.0f}  {r['ret_945_on_pct']:>+9.2f}%  "
                f"{r['ret_945_off_pct']:>+9.2f}%  {r['diff_ret_pp']:>+7.2f}"
            )
        print(
            f"  {'合计':>4}  {ydiff['end_945_on'].iloc[-1]:>12,.0f}  "
            f"{ydiff['end_945_off'].iloc[-1]:>12,.0f}  "
            f"{ydiff['diff_yuan'].iloc[-1]:>+12,.0f}"
        )
    print()
    print("【单次事件对比】（持有时 + 确定945前未翻红，共 {} 次）".format(n))
    if n:
        print(f"  945卖更优: {sell_wins} 次 ({sell_wins/n*100:.1f}%)")
        print(f"  不卖更优: {hold_wins} 次 ({hold_wins/n*100:.1f}%)")
        print(f"  持平:     {tie} 次")
        print(f"  945卖平均单笔收益: {ev['pnl945_pct'].mean():+.2f}%")
        print(f"  不卖平均单笔收益:   {ev['pnl_no945_pct'].mean():+.2f}%")
        print(f"  平均差额(945-不卖): {ev['diff_pct'].mean():+.2f} pp")
        print(f"  945卖累计差额合计: {ev['diff_pct'].sum():+.2f} pp（非组合复利）")
        print()
        print("  明细（945卖 vs 不卖，按差额排序）:")
        show = ev.sort_values("diff_pct", ascending=False)
        for _, r in show.iterrows():
            print(
                f"    {r['day']} entry={r['entry']:.2f} "
                f"945={r['exit945']:.2f}({r['exit945_src']})→{r['pnl945_pct']:+.2f}% | "
                f"不卖={r['no945_px']:.2f}({r['no945_reason']})→{r['pnl_no945_pct']:+.2f}% | "
                f"差{r['diff_pct']:+.2f}% [{r['better']}]"
            )

    print()
    print("说明:")
    print("  · 无历史1分钟线时，945卖价用开盘价近似，实际945价可能略高或略低。")
    print("  · 「不卖」= 当日仍按原策略：止损 > 阴线收盘 > 阳/十字持有至收盘。")
    print("  · 全区间回测含 proxy 下全部低开未翻红日，非仅 49 次持仓事件。")


if __name__ == "__main__":
    main()
