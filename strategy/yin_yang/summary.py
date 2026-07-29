"""日线阴阳策略 — 回测摘要。"""

from __future__ import annotations

import pandas as pd
from akquant import BacktestResult

from strategy.yin_yang.config import YinYangConfig


def _metric(metrics_df: pd.DataFrame, name: str) -> float:
    if name not in metrics_df.index:
        return float("nan")
    return float(metrics_df.loc[name, "value"])


def print_summary(
    result: BacktestResult,
    data: pd.DataFrame,
    *,
    cfg: YinYangConfig,
) -> None:
    m = result.metrics_df
    c0 = float(data.iloc[0]["close"])
    c1 = float(data.iloc[-1]["close"])
    bh = (c1 / c0 - 1.0) * 100.0

    print("\n========== 回测摘要 (YinYang) ==========")
    print(f"标的: {cfg.symbol_name} ({cfg.symbol})")
    print(f"区间: {data['date'].iloc[0]} → {data['date'].iloc[-1]}")
    print("规则: 收阳买 / 收阴卖")
    print(f"总盈亏: {_metric(m, 'total_pnl'):.2f}")
    print(f"累计收益%: {_metric(m, 'total_return_pct'):.4f}")
    print(f"最大回撤%: {_metric(m, 'max_drawdown_pct'):.4f}")
    print(f"胜率%: {_metric(m, 'win_rate'):.4f}")
    print(f"闭环交易: {_metric(m, 'closed_trade_count'):.0f}")
    print(f"期末市值: {_metric(m, 'end_market_value'):.2f}")
    print(f"买入持有: {bh:.2f}%  ({c0:.2f} → {c1:.2f})")
