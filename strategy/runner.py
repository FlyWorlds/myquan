"""OpenBreak3 / 动量 统一回测入口。"""

from __future__ import annotations

import pandas as pd
from akquant import BacktestResult, CurrentClose, NextOpen, Strategy

from strategy.backtest import OpenBreak3Strategy, print_summary
from strategy.base import run_akquant_backtest, run_backtest_pipeline
from strategy.config import BacktestConfig
from strategy.momentum_strategy import (
    MomentumStrategy,
    apply_momentum_config,
    prepare_momentum_signals,
)

_FILL = CurrentClose()
_FILL_NEXT_OPEN = NextOpen()


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
    from strategy.open_break import (
        DEFAULT_BAN_DOUBLE_YANG,
        DEFAULT_BAN_SINGLE_YANG,
        DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
        DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    )

    strategy.ban_double_yang = bool(
        getattr(cfg, "ban_double_yang", DEFAULT_BAN_DOUBLE_YANG)
    )
    strategy.ban_single_yang = bool(
        getattr(cfg, "ban_single_yang", DEFAULT_BAN_SINGLE_YANG)
    )
    strategy.yang_min_pct = float(getattr(cfg, "yang_min_pct", 0.0) or 0.0)
    sec = getattr(cfg, "double_yang_second_min_pct", None)
    strategy.double_yang_second_min_pct = float(sec) if sec is not None else None
    comb = getattr(cfg, "double_yang_combined_min_pct", DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT)
    strategy.double_yang_combined_min_pct = float(comb) if comb is not None else None
    mode = str(
        getattr(cfg, "double_yang_combined_mode", DEFAULT_DOUBLE_YANG_COMBINED_MODE)
        or DEFAULT_DOUBLE_YANG_COMBINED_MODE
    )
    strategy.double_yang_combined_mode = (
        mode if mode in ("sum_body", "span") else DEFAULT_DOUBLE_YANG_COMBINED_MODE
    )
    smin = getattr(cfg, "single_yang_min_pct", None)
    strategy.single_yang_min_pct = float(smin) if smin is not None else None
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
    strategy.skip_buy_after_consec_stops = int(
        getattr(cfg, "skip_buy_after_consec_stops", 0) or 0
    )
    strategy.skip_buy_after_overnight_stop = bool(
        getattr(cfg, "skip_buy_after_overnight_stop", False)
    )
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


def run_momentum(
    cfg: BacktestConfig,
    *,
    show_report: bool = False,
    verbose: bool = True,
    force_daily_refresh: bool = False,
) -> tuple[BacktestResult, pd.DataFrame]:
    """因子3·动量：收盘确认信号 → 次日开盘成交。

    先用更长历史预热因子（避免 dig 窗口起点丢状态），再截到 cfg.start_date 回测。
    """
    from strategy.data import fetch_daily

    kind = getattr(cfg, "mom_kind", "dist_hl") or "dist_hl"
    params = getattr(cfg, "mom_params", None) or {}
    warm_start = "20200101"
    if verbose:
        print(f"akquant 动量回测 kind={kind} params={params}")
        print(
            f"拉取 {cfg.symbol_name}({cfg.symbol}) "
            f"日线预热 {warm_start} → {cfg.end_date}，回测自 {cfg.start_date} ..."
        )
    full = fetch_daily(
        cfg.symbol,
        warm_start,
        cfg.end_date,
        cache_path=getattr(cfg, "daily_cache", None),
        force_refresh=force_daily_refresh,
    )
    prepare_momentum_signals(cfg, full)
    start_ts = pd.Timestamp(cfg.start_date)
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize("Asia/Shanghai")
    daily = full[full["date"] >= start_ts].reset_index(drop=True)
    if verbose:
        print(
            f"预热后回测日线: {len(daily)}，"
            f"{daily['date'].iloc[0]} → {daily['date'].iloc[-1]}"
        )

    from strategy.base import run_akquant_backtest

    result = run_akquant_backtest(
        daily=daily,
        strategy_cls=MomentumStrategy,
        symbol=cfg.symbol,
        params=cfg,
        configure=apply_momentum_config,
        extra={
            "t_plus_one": not bool(cfg.t0),
            "fill_policy": _FILL_NEXT_OPEN,
            "timezone": "Asia/Shanghai",
            "show_progress": False,
        },
    )
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
            entry_pct=0.0,
            stop_pct=0.0,
            prev_small_yang_pct=0.0,
        )
    if cfg.report_path is not None:
        title = f"{cfg.symbol_name} 因子3·动量 kind={kind} params={params}"
        if verbose:
            print(f"\n生成 HTML: {cfg.report_path}")
        result.viz.report(
            title=title,
            filename=str(cfg.report_path),
            show=show_report,
            market_data=daily,
            plot_symbol=cfg.symbol,
            curve_freq="D",
        )
        if verbose:
            print(f"报告已生成: {cfg.report_path}")
    return result, daily
