"""打板战法 — 回测摘要 + 涨停样本统计。"""

from __future__ import annotations

import pandas as pd
from akquant import BacktestResult

from strategy.daban.config import DaBanConfig
from strategy.daban.rules import is_sealed_limit_up, limit_up_price


def _metric(metrics_df: pd.DataFrame, name: str) -> float:
    if name not in metrics_df.index:
        return float("nan")
    return float(metrics_df.loc[name, "value"])


def count_sealed_limit_ups(data: pd.DataFrame, cfg: DaBanConfig) -> int:
    n = 0
    for i in range(1, len(data)):
        prev_c = float(data.iloc[i - 1]["close"])
        row = data.iloc[i]
        if is_sealed_limit_up(
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
            prev_c,
            limit_pct=cfg.limit_pct,
            seal_high_ticks=cfg.seal_high_ticks,
        ):
            n += 1
    return n


def print_summary(
    result: BacktestResult,
    data: pd.DataFrame,
    *,
    cfg: DaBanConfig,
) -> None:
    m = result.metrics_df
    c0 = float(data.iloc[0]["close"])
    c1 = float(data.iloc[-1]["close"])
    bh = (c1 / c0 - 1.0) * 100.0
    sealed = count_sealed_limit_ups(data, cfg)

    print("\n========== 回测摘要 (DaBan 打板) ==========")
    print(f"标的: {cfg.symbol_name} ({cfg.symbol})")
    print(f"区间: {data['date'].iloc[0]} → {data['date'].iloc[-1]}")
    print(
        f"规则: 涨停{cfg.limit_pct*100:.0f}%封板买 | "
        f"低开≥{cfg.gap_down_exit_pct*100:.0f}%开盘卖 | 不连板收盘卖"
    )
    print(f"历史封板涨停日: {sealed} 天")
    print(f"总盈亏: {_metric(m, 'total_pnl'):.2f}")
    print(f"累计收益%: {_metric(m, 'total_return_pct'):.4f}")
    print(f"最大回撤%: {_metric(m, 'max_drawdown_pct'):.4f}")
    print(f"胜率%: {_metric(m, 'win_rate'):.4f}")
    print(f"闭环交易: {_metric(m, 'closed_trade_count'):.0f}")
    print(f"期末市值: {_metric(m, 'end_market_value'):.2f}")
    print(f"买入持有: {bh:.2f}%  ({c0:.2f} → {c1:.2f})")

    # 最近几次封板日（供对照）
    rows: list[str] = []
    for i in range(1, len(data)):
        prev_c = float(data.iloc[i - 1]["close"])
        row = data.iloc[i]
        o, h, low, c = (
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
        )
        if not is_sealed_limit_up(
            o, h, low, c, prev_c,
            limit_pct=cfg.limit_pct,
            seal_high_ticks=cfg.seal_high_ticks,
        ):
            continue
        ts = pd.to_datetime(row["date"])
        day = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(row["date"])[:10]
        lu = limit_up_price(prev_c, cfg.limit_pct)
        rows.append(f"  {day}  涨停价≈{lu:.2f}  收={c:.2f}")
    if rows:
        print("\n封板日样本（最近 8 个）:")
        for line in rows[-8:]:
            print(line)
