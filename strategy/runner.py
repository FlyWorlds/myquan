"""OpenBreak3 统一回测入口。"""

from __future__ import annotations

import pandas as pd
from akquant import BacktestResult, CurrentClose, Strategy

from strategy.backtest import OpenBreak3Strategy, print_summary
from strategy.base import run_akquant_backtest, run_backtest_pipeline
from strategy.config import BacktestConfig

_FILL = CurrentClose()


def apply_strategy_config(
    strategy: Strategy,
    cfg: BacktestConfig,
) -> Strategy:
    """把配置写到**策略实例**上，避免类属性在并行回测中互相覆盖。"""
    strategy.symbol = cfg.symbol
    strategy.symbol_name = cfg.symbol_name
    strategy.target_pct = cfg.target_pct
    strategy.lot_size = cfg.lot_size
    strategy.start_date = cfg.start_date
    strategy.end_date = cfg.end_date
    strategy.slippage_value = cfg.slippage_value
    strategy.entry_pct = cfg.threshold_pct
    strategy.stop_pct = cfg.threshold_pct
    strategy.prev_small_yang_pct = cfg.threshold_pct
    strategy.tick = cfg.tick
    strategy.limit_down_pct = cfg.limit_down_pct
    strategy.t0 = cfg.t0
    strategy.entry_ref = getattr(cfg, "entry_ref", "today_open") or "today_open"
    strategy.prev_entry_mode = (
        getattr(cfg, "prev_entry_mode", "yin_or_small_yang") or "yin_or_small_yang"
    )
    levels = getattr(cfg, "take_profit_levels", None)
    strategy.take_profit_levels = tuple(levels) if levels else ()
    strategy.take_profit_reduce = float(getattr(cfg, "take_profit_reduce", 0.20) or 0.0)
    trig = str(getattr(cfg, "take_profit_trigger", "high") or "high").lower()
    strategy.take_profit_trigger = trig if trig in ("high", "close") else "high"
    strategy.take_profit_limit_offset = float(
        getattr(cfg, "take_profit_limit_offset", 0.0) or 0.0
    )
    lock = getattr(cfg, "take_profit_lock_pct", None)
    strategy.take_profit_lock_pct = float(lock) if lock is not None else None
    return strategy


def build_open_break_strategy(cfg: BacktestConfig) -> OpenBreak3Strategy:
    """构造已绑定配置的策略实例。"""
    return apply_strategy_config(OpenBreak3Strategy(), cfg)  # type: ignore[return-value]


def run_open_break_backtest(
    cfg: BacktestConfig,
    daily: pd.DataFrame,
) -> BacktestResult:
    return run_akquant_backtest(
        daily=daily,
        strategy_cls=OpenBreak3Strategy,
        symbol=cfg.symbol,
        params=cfg,
        configure=apply_strategy_config,
        extra={
            "t_plus_one": not bool(cfg.t0),
            "fill_policy": _FILL,
            "timezone": "Asia/Shanghai",
            "show_progress": False,
        },
    )


def run_open_break(
    cfg: BacktestConfig,
    *,
    show_report: bool = False,
    verbose: bool = True,
    force_daily_refresh: bool = False,
) -> tuple[BacktestResult, pd.DataFrame]:
    """拉数据 → 回测 → 摘要 → 可选 HTML 报告。

    force_daily_refresh=True 会忽略本地日线缓存，重拉完整历史区间。
    """
    return run_backtest_pipeline(
        params=cfg,
        strategy_cls=OpenBreak3Strategy,
        configure=apply_strategy_config,
        print_summary_fn=print_summary if verbose else None,
        summary_kwargs={
            "symbol_name": cfg.symbol_name,
            "symbol": cfg.symbol,
            "initial_cash": cfg.initial_cash,
            "commission_rate": cfg.commission_rate,
            "stamp_tax_rate": cfg.stamp_tax_rate,
            "slippage_value": cfg.slippage_value,
            "entry_pct": cfg.threshold_pct,
            "stop_pct": cfg.threshold_pct,
            "prev_small_yang_pct": cfg.threshold_pct,
        },
        report_title=f"{cfg.symbol_name} {cfg.report_title_suffix()}",
        show_report=show_report,
        verbose=verbose,
        force_daily_refresh=force_daily_refresh,
        extra={
            "t_plus_one": not bool(cfg.t0),
            "fill_policy": _FILL,
            "timezone": "Asia/Shanghai",
            "show_progress": False,
        },
    )
