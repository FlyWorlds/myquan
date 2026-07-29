"""超跌反弹形态 — 事件驱动历史回测（次日买卖）。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from strategy.oversold_bounce.stats import ScanConfig


@dataclass(frozen=True)
class TradeScenario:
    key: str
    label: str
    entry_col: str
    exit_col: str


SCENARIOS: tuple[TradeScenario, ...] = (
    TradeScenario(
        "close_close",
        "信号日收盘买 → 次日收盘卖",
        "close",
        "next_close",
    ),
    TradeScenario(
        "close_open",
        "信号日收盘买 → 次日开盘卖",
        "close",
        "next_open",
    ),
    TradeScenario(
        "open_close",
        "次日开盘买 → 次日收盘卖",
        "next_open",
        "next_close",
    ),
    TradeScenario(
        "close_high",
        "信号日收盘买 → 次日最高卖(理想)",
        "close",
        "next_high",
    ),
)


def _trade_return_pct(row: pd.Series, sc: TradeScenario) -> float:
    entry = float(row[sc.entry_col])
    exit_px = float(row[sc.exit_col])
    if entry <= 0:
        return float("nan")
    return (exit_px / entry - 1.0) * 100.0


def build_scenario_returns(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    out = events[["signal_day", "next_day", "close"]].copy()
    out = out.rename(columns={"close": "sig_close"})
    for sc in SCENARIOS:
        out[sc.key] = events.apply(lambda r, s=sc: _trade_return_pct(r, s), axis=1)
    return out


def _compound_return(pcts: pd.Series) -> float:
    eq = 1.0
    for r in pcts.dropna():
        eq *= 1.0 + float(r) / 100.0
    return (eq - 1.0) * 100.0


def _summarize_series(pcts: pd.Series) -> dict[str, float | int]:
    s = pcts.dropna()
    n = len(s)
    if n == 0:
        return {"n": 0, "mean": float("nan"), "median": float("nan"), "win": 0}
    win = int((s > 0).sum())
    return {
        "n": n,
        "mean": float(s.mean()),
        "median": float(s.median()),
        "max": float(s.max()),
        "min": float(s.min()),
        "win": win,
        "win_rate": win / n * 100.0,
        "compound": _compound_return(s),
        "sum": float(s.sum()),
    }


def buy_hold_return(daily: pd.DataFrame, start: str, end: str) -> float | None:
    df = daily.copy()
    ts = pd.to_datetime(df["date"])
    if ts.dt.tz is not None:
        ts = ts.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    df["day"] = ts.dt.strftime("%Y%m%d")
    sub = df[(df["day"] >= start) & (df["day"] <= end)]
    if len(sub) < 2:
        return None
    c0 = float(sub.iloc[0]["close"])
    c1 = float(sub.iloc[-1]["close"])
    if c0 <= 0:
        return None
    return (c1 / c0 - 1.0) * 100.0


def print_backtest_report(
    cfg: ScanConfig,
    events: pd.DataFrame,
    daily: pd.DataFrame,
) -> pd.DataFrame:
    print("【历史回测 · 单次信号独立交易】")
    if events.empty:
        print("  (样本不足，无法回测)")
        print()
        return pd.DataFrame()

    trades = build_scenario_returns(events)
    print(f"  样本: {len(trades)} 笔  |  每笔全仓单利测算（信号不重叠时复利见下表）")
    print()
    print(f"  {'策略':<28} {'均收益':>7} {'中位':>7} {'复利':>7} {'胜率':>8} {'笔数':>4}")
    print(f"  {'-'*28} {'-'*7} {'-'*7} {'-'*7} {'-'*8} {'-'*4}")
    for sc in SCENARIOS:
        sm = _summarize_series(trades[sc.key])
        print(
            f"  {sc.label:<28} {sm['mean']:>+6.2f}% {sm['median']:>+6.2f}% "
            f"{sm['compound']:>+6.2f}% {sm['win']}/{sm['n']}({sm['win_rate']:.0f}%) {sm['n']:>4}"
        )

    bh = buy_hold_return(daily, cfg.start_date, cfg.end_date)
    if bh is not None:
        print()
        print(f"  同期买入持有({cfg.symbol_name}): {bh:+.2f}%")

    print()
    print("【回测明细 · 信号日收盘买→次日收盘卖】")
    print(
        f"  {'信号日':<12} {'买入':>7} {'卖出日':<12} {'卖出':>7} {'收益%':>7}"
    )
    for _, r in trades.iterrows():
        sig = events.loc[events["signal_day"] == r["signal_day"]].iloc[0]
        ret = float(r["close_close"])
        print(
            f"  {r['signal_day']:<12} {r['sig_close']:>7.2f} {r['next_day']:<12} "
            f"{float(sig['next_close']):>7.2f} {ret:>+7.2f}"
        )
    print()
    return trades
