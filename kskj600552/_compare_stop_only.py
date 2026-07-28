"""对比两种止损成交方式（阴线规则相同：收盘卖）.

1. 止损@触发价：low 触 open-2.5% → 按 floor(open×0.975) 限价卖
2. 触止损@尾盘：low 触 open-2.5% → 按收盘价限价卖（盘中未成交、尾盘兜底）
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import akquant as aq
import pandas as pd

_PATH = Path(__file__).with_name("kskj.py")
spec = importlib.util.spec_from_file_location("kskj", _PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class StopAtCloseStrategy(m.OpenBreak3Strategy):
    """low 触止损线后，按收盘价卖出（模拟尾盘兜底）。"""

    def on_start(self) -> None:
        super().on_start()
        self.log("变体: low 触止损 → 收盘价卖出(尾盘)")

    def on_bar(self, bar) -> None:
        if bar.symbol != m.SYMBOL:
            return

        o = float(bar.open)
        h = float(bar.high)
        low = float(bar.low)
        c = float(bar.close)
        day = self.to_local_time(bar.timestamp).strftime("%Y-%m-%d")

        bought_today = False
        try:
            pos = self._sync_position_state()
            entry_px = m.entry_trigger_price(o)
            stop_px = m.stop_trigger_price(o)
            hit_entry = h + 1e-12 >= entry_px
            hit_stop = low <= stop_px + 1e-12
            yin = m.is_yin(o, c)

            if self.armed and pos <= 0 and hit_entry:
                can_buy = (
                    self.prev_open is not None
                    and self.prev_close is not None
                    and m.prev_day_allows_entry(self.prev_open, self.prev_close)
                    and not m.has_double_yang_before(
                        self.prev2_open,
                        self.prev2_close,
                        self.prev_open,
                        self.prev_close,
                    )
                )
                if can_buy:
                    self.order_target_percent(
                        symbol=m.SYMBOL, target_percent=m.TARGET_PCT, price=entry_px
                    )
                    self.armed = False
                    self.entry_price = entry_px
                    self.buy_day = day
                    bought_today = True

            if bought_today or self.buy_day == day:
                return

            pos = float(self.get_position(m.SYMBOL))
            avail = float(self.get_available_position(m.SYMBOL))
            if pos <= 0 and avail <= 0:
                return

            if hit_stop:
                self._exit_all(
                    day=day,
                    avail=avail,
                    pos=pos,
                    price=float(c),
                    reason=f"触止损尾盘卖 stop={stop_px:.2f} close={c:.2f}",
                )
                return

            if yin:
                self._exit_all(
                    day=day,
                    avail=avail,
                    pos=pos,
                    price=float(c),
                    reason="阴线收盘卖出",
                )
        finally:
            self._roll_prev_bars(o, c)


def _stop_exit_stats(result: aq.BacktestResult) -> dict:
    """统计止损卖出笔数及相对触发价的价差。"""
    ex = result.executions_df
    if ex is None or ex.empty:
        return {"stop_n": 0, "avg_slip_vs_stop": float("nan")}
    side = ex.get("side", pd.Series(dtype=str)).astype(str).str.lower()
    sells = ex[side == "sell"].copy()
    if sells.empty:
        return {"stop_n": 0, "avg_slip_vs_stop": float("nan")}
    # 日志里含「止损」或「触止损」
    reason_col = next((c for c in ("reason", "comment", "message") if c in sells.columns), None)
    if reason_col is None:
        return {"stop_n": 0, "avg_slip_vs_stop": float("nan")}
    stop_mask = sells[reason_col].astype(str).str.contains("止损|触止损", regex=True)
    stop_sells = sells[stop_mask]
    return {"stop_n": int(len(stop_sells)), "avg_slip_vs_stop": float("nan")}


def run(label: str, strategy_cls: type) -> dict:
    daily = m.fetch_daily(m.SYMBOL, m.START_DATE, m.END_DATE)
    r = aq.run_backtest(
        data=daily,
        strategy=strategy_cls,
        symbols=m.SYMBOL,
        initial_cash=m.INITIAL_CASH,
        commission_rate=m.COMMISSION_RATE,
        stamp_tax_rate=m.STAMP_TAX_RATE,
        t_plus_one=True,
        lot_size=m.LOT_SIZE,
        fill_policy=m.FILL_CLOSE,
        slippage=m.SLIPPAGE,
        timezone="Asia/Shanghai",
        show_progress=False,
    )
    met = r.metrics_df
    end = float(r.equity_curve_daily.iloc[-1])
    ret = (end / m.INITIAL_CASH - 1) * 100
    dd = float(met.loc["max_drawdown_pct", "value"]) if "max_drawdown_pct" in met.index else float("nan")
    n = int(met.loc["closed_trade_count", "value"]) if "closed_trade_count" in met.index else 0
    wr = float(met.loc["win_rate", "value"]) if "win_rate" in met.index else float("nan")
    extra = _stop_exit_stats(r)
    return {
        "label": label,
        "end_eq": end,
        "ret%": ret,
        "dd%": dd,
        "trades": n,
        "win%": wr,
        **extra,
    }


def diff_stop_days() -> pd.DataFrame:
    """逐日对比：触止损日两种卖价差异。"""
    daily = m.fetch_daily(m.SYMBOL, m.START_DATE, m.END_DATE)
    rows = []
    for _, r in daily.iterrows():
        o, low, c = float(r["open"]), float(r["low"]), float(r["close"])
        sp = m.stop_trigger_price(o)
        if low <= sp + 1e-12:
            rows.append(
                {
                    "date": r["date"],
                    "open": o,
                    "low": low,
                    "close": c,
                    "stop_px": sp,
                    "at_stop": sp,
                    "at_close": c,
                    "close_minus_stop": c - sp,
                    "gap_open": o < sp - 1e-12,
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    variants = [
        ("① 止损@触发价", m.OpenBreak3Strategy),
        ("② 触止损@尾盘(收盘)", StopAtCloseStrategy),
    ]
    rows = [run(l, c) for l, c in variants]
    df = pd.DataFrame(rows)

    print("=" * 64)
    print(f"{m.SYMBOL_NAME}  止损成交方式对比（阴线仍@收盘）")
    print(f"区间: {m.START_DATE} ~ {m.END_DATE}")
    print("=" * 64)
    for _, r in df.iterrows():
        print(
            f"{r['label']:20}  收益 {r['ret%']:+.2f}%  "
            f"回撤 {r['dd%']:.2f}%  闭环 {int(r['trades'])}  "
            f"胜率 {r['win%']:.1f}%  期末 {r['end_eq']:,.0f}"
        )
    if len(df) == 2:
        a, b = df.iloc[0], df.iloc[1]
        print(f"\n差异(②-①): 收益 {b['ret%']-a['ret%']:+.2f}pp  期末 {b['end_eq']-a['end_eq']:+,.0f}")

    sd = diff_stop_days()
    if not sd.empty:
        n = len(sd)
        worse = int((sd["close_minus_stop"] < -1e-8).sum())
        better = int((sd["close_minus_stop"] > 1e-8).sum())
        same = n - worse - better
        gap = int(sd["gap_open"].sum())
        print(f"\n--- 触止损交易日分析（共 {n} 天，不含持仓过滤）---")
        print(f"  收盘 < 触发价（尾盘卖更差）: {worse} 天  平均差 {sd.loc[sd['close_minus_stop']<0,'close_minus_stop'].mean():+.3f} 元")
        print(f"  收盘 > 触发价（尾盘卖更好）: {better} 天  平均差 {sd.loc[sd['close_minus_stop']>0,'close_minus_stop'].mean():+.3f} 元")
        print(f"  收盘 = 触发价: {same} 天")
        print(f"  低开已破止损(open<stop): {gap} 天 → 条件单难成交、尾盘兜底典型场景")

    print("\n说明:")
    print("  ① 回测假设 low 触线可按触发价成交（理想条件单）")
    print("  ② 触线后一律按收盘价卖（盘中未成交、尾盘强平）")
    print("  阴线卖出两版相同；差异仅来自止损成交方式")


if __name__ == "__main__":
    main()
