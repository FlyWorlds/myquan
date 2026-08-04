"""OpenBreak3 统一回测入口。"""

from __future__ import annotations

import akquant as aq
import pandas as pd
from akquant import BacktestResult, CurrentClose

from strategy.backtest import OpenBreak3Strategy, print_summary
from strategy.data import fetch_daily
from strategy.config import BacktestConfig

_FILL = CurrentClose()


def apply_strategy_config(
    cfg: BacktestConfig,
) -> None:
    OpenBreak3Strategy.symbol = cfg.symbol
    OpenBreak3Strategy.symbol_name = cfg.symbol_name
    OpenBreak3Strategy.target_pct = cfg.target_pct
    OpenBreak3Strategy.lot_size = cfg.lot_size
    OpenBreak3Strategy.start_date = cfg.start_date
    OpenBreak3Strategy.end_date = cfg.end_date
    OpenBreak3Strategy.slippage_value = cfg.slippage_value
    OpenBreak3Strategy.entry_pct = cfg.threshold_pct
    OpenBreak3Strategy.stop_pct = cfg.threshold_pct
    OpenBreak3Strategy.prev_small_yang_pct = cfg.threshold_pct
    OpenBreak3Strategy.tick = cfg.tick
    OpenBreak3Strategy.t0 = cfg.t0
    OpenBreak3Strategy.entry_ref = getattr(cfg, "entry_ref", "today_open") or "today_open"
    OpenBreak3Strategy.prev_entry_mode = (
        getattr(cfg, "prev_entry_mode", "yin_or_small_yang") or "yin_or_small_yang"
    )


def run_open_break_backtest(
    cfg: BacktestConfig,
    daily: pd.DataFrame,
) -> BacktestResult:
    apply_strategy_config(cfg)
    return aq.run_backtest(
        data=daily,
        strategy=OpenBreak3Strategy,
        symbols=cfg.symbol,
        initial_cash=cfg.initial_cash,
        commission_rate=cfg.commission_rate,
        stamp_tax_rate=cfg.stamp_tax_rate,
        t_plus_one=not bool(cfg.t0),
        lot_size=cfg.lot_size,
        fill_policy=_FILL,
        slippage=cfg.slippage,
        timezone="Asia/Shanghai",
        show_progress=False,
    )


def run_open_break(
    cfg: BacktestConfig,
    *,
    show_report: bool = False,
    verbose: bool = True,
) -> tuple[BacktestResult, pd.DataFrame]:
    """拉数据 → 回测 → 摘要 → 可选 HTML 报告。"""
    if verbose:
        print(f"akquant={getattr(aq, '__version__', '?')}")
        print(f"拉取 {cfg.symbol_name}({cfg.symbol}) 日线 {cfg.start_date} → {cfg.end_date} ...")

    daily = fetch_daily(cfg.symbol, cfg.start_date, cfg.end_date)
    if verbose:
        print(
            f"日线数: {len(daily)}，"
            f"区间: {daily['date'].iloc[0]} → {daily['date'].iloc[-1]}"
        )

    result = run_open_break_backtest(cfg, daily)

    if verbose:
        print("\n=== Backtest Result ===")
        print(result)
        print_summary(
            result,
            daily,
            symbol_name=cfg.symbol_name,
            symbol=cfg.symbol,
            initial_cash=cfg.initial_cash,
            commission_rate=cfg.commission_rate,
            stamp_tax_rate=cfg.stamp_tax_rate,
            slippage_value=cfg.slippage_value,
            entry_pct=cfg.threshold_pct,
            stop_pct=cfg.threshold_pct,
            prev_small_yang_pct=cfg.threshold_pct,
        )

    report_path = cfg.report_path
    if report_path is not None:
        if verbose:
            print(f"\n生成 HTML: {report_path}")
        result.viz.report(
            title=f"{cfg.symbol_name} {cfg.report_title_suffix()}",
            filename=str(report_path),
            show=show_report,
            market_data=daily,
            plot_symbol=cfg.symbol,
            curve_freq="D",
        )
        if verbose:
            print(f"报告已生成: {report_path}")

    return result, daily
