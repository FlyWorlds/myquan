"""多策略共用：akquant 回测骨架。

新策略只需实现：
  1. rules.py   — 纯函数 / 常量 / STRATEGY_RULES / 盯盘 signal（可选）
  2. backtest.py — akquant Strategy 子类
  3. config.py  — dataclass 配置 + 标的预设
  4. runner.py  — prepare + run_xxx()，内部调用 run_akquant_backtest
  5. huice/xxx.py — 薄 CLI

然后在 registry.py 注册即可。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Type

import akquant as aq
import pandas as pd
from akquant import BacktestResult, CurrentClose, Strategy

from strategy.data import fetch_daily

_FILL = CurrentClose()


@dataclass
class CommonBacktestParams:
    """各策略 config 建议包含的公共字段。"""

    symbol: str
    symbol_name: str
    start_date: str
    end_date: str
    initial_cash: float = 100_000.0
    lot_size: int = 100
    commission_rate: float = 0.0000854
    stamp_tax_rate: float = 0.001
    slippage_value: float = 0.001
    report_path: Path | None = None

    @property
    def slippage(self) -> dict[str, str | float]:
        return {"type": "percent", "value": self.slippage_value}


def run_akquant_backtest(
    *,
    daily: pd.DataFrame,
    strategy_cls: Type[Strategy],
    symbol: str,
    params: CommonBacktestParams | Any,
    configure: Callable[[Type[Strategy], Any], None] | None = None,
    extra: dict[str, Any] | None = None,
) -> BacktestResult:
    """通用 akquant 回测：configure 负责给 Strategy 类属性赋值。"""
    if configure is not None:
        configure(strategy_cls, params)
    kw = extra or {}
    return aq.run_backtest(
        data=daily,
        strategy=strategy_cls,
        symbols=symbol,
        initial_cash=params.initial_cash,
        commission_rate=params.commission_rate,
        stamp_tax_rate=params.stamp_tax_rate,
        t_plus_one=kw.get("t_plus_one", True),
        lot_size=params.lot_size,
        fill_policy=kw.get("fill_policy", _FILL),
        slippage=params.slippage,
        timezone=kw.get("timezone", "Asia/Shanghai"),
        show_progress=kw.get("show_progress", False),
    )


def run_backtest_pipeline(
    *,
    params: CommonBacktestParams | Any,
    strategy_cls: Type[Strategy],
    configure: Callable[[Type[Strategy], Any], None],
    prepare: Callable[[Any, pd.DataFrame], Any] | None = None,
    print_summary_fn: Callable[..., None] | None = None,
    summary_kwargs: dict[str, Any] | None = None,
    report_title: str | None = None,
    show_report: bool = False,
    verbose: bool = True,
) -> tuple[BacktestResult, pd.DataFrame]:
    """拉日线 → 可选 prepare → 回测 → 摘要 → 可选 HTML。"""
    if verbose:
        print(f"akquant={getattr(aq, '__version__', '?')}")
        print(
            f"拉取 {params.symbol_name}({params.symbol}) "
            f"日线 {params.start_date} → {params.end_date} ..."
        )

    daily = fetch_daily(params.symbol, params.start_date, params.end_date)
    if verbose:
        print(
            f"日线数: {len(daily)}，"
            f"区间: {daily['date'].iloc[0]} → {daily['date'].iloc[-1]}"
        )

    if prepare is not None:
        prepare(params, daily)

    result = run_akquant_backtest(
        daily=daily,
        strategy_cls=strategy_cls,
        symbol=params.symbol,
        params=params,
        configure=configure,
    )

    if verbose and print_summary_fn is not None:
        print("\n=== Backtest Result ===")
        print(result)
        sk = summary_kwargs or {}
        print_summary_fn(result, daily, **sk)

    if params.report_path is not None:
        title = report_title or f"{params.symbol_name} ({params.start_date}~{params.end_date})"
        if verbose:
            print(f"\n生成 HTML: {params.report_path}")
        result.viz.report(
            title=title,
            filename=str(params.report_path),
            show=show_report,
            market_data=daily,
            plot_symbol=params.symbol,
            curve_freq="D",
        )
        if verbose:
            print(f"报告已生成: {params.report_path}")

    return result, daily
