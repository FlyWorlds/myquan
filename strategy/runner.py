"""OpenBreak3 统一回测入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import akquant as aq
import pandas as pd
from akquant import BacktestResult, CurrentClose

from strategy.backtest import OpenBreak3Strategy, print_summary
from strategy.data import fetch_daily
from strategy.config import BacktestConfig
from strategy.minute import fetch_minute_1m
from strategy.open_break import (
    build_gap_down_945_map,
    build_gap_down_945_proxy_map,
    build_pullback_half_map,
)

_FILL = CurrentClose()


def build_gap_map(
    cfg: BacktestConfig,
    daily: pd.DataFrame,
    minute: pd.DataFrame,
) -> dict[str, dict[str, float | str]]:
    if not cfg.enable_gap945:
        return {}
    if cfg.gap945_use_proxy:
        return build_gap_down_945_proxy_map(
            daily,
            minute,
            proxy=cfg.gap945_proxy,
            exit_mode=cfg.gap945_exit_mode,
        )
    return build_gap_down_945_map(daily, minute, exit_mode=cfg.gap945_exit_mode)


def load_minute(cfg: BacktestConfig) -> pd.DataFrame:
    cache = cfg.min1_cache or Path(f"{cfg.symbol}_1m_qfq.parquet")
    return fetch_minute_1m(
        sina_symbol=cfg.symbol,
        em_symbol=cfg.em_symbol,
        cache_path=cache,
        start_date=cfg.start_date,
        end_date=cfg.end_date,
    )


def apply_strategy_config(
    cfg: BacktestConfig,
    gap_map: dict[str, dict[str, float | str]],
    *,
    pullback_half_map: dict[str, dict[str, float | str]] | None = None,
) -> None:
    OpenBreak3Strategy.symbol = cfg.symbol
    OpenBreak3Strategy.symbol_name = cfg.symbol_name
    OpenBreak3Strategy.target_pct = cfg.target_pct
    OpenBreak3Strategy.lot_size = cfg.lot_size
    OpenBreak3Strategy.start_date = cfg.start_date
    OpenBreak3Strategy.end_date = cfg.end_date
    OpenBreak3Strategy.slippage_value = cfg.slippage_value
    OpenBreak3Strategy.gap_down_945_map = gap_map
    OpenBreak3Strategy.pullback_half_map = pullback_half_map or {}
    OpenBreak3Strategy.enable_gap945 = cfg.enable_gap945
    OpenBreak3Strategy.entry_pct = cfg.threshold_pct
    OpenBreak3Strategy.stop_pct = cfg.threshold_pct
    OpenBreak3Strategy.prev_small_yang_pct = cfg.threshold_pct
    OpenBreak3Strategy.tick = cfg.tick
    OpenBreak3Strategy.t0 = cfg.t0
    OpenBreak3Strategy.entry_ref = getattr(cfg, "entry_ref", "today_open") or "today_open"
    OpenBreak3Strategy.prev_entry_mode = (
        getattr(cfg, "prev_entry_mode", "yin_or_small_yang") or "yin_or_small_yang"
    )
    OpenBreak3Strategy.enable_factor2 = bool(getattr(cfg, "enable_factor2", False))
    OpenBreak3Strategy.pullback_pct = float(
        getattr(cfg, "pullback_pct", 0.025) or 0.025
    )


def run_open_break_backtest(
    cfg: BacktestConfig,
    daily: pd.DataFrame,
    *,
    gap_map: dict[str, dict[str, float | str]] | None = None,
    pullback_half_map: dict[str, dict[str, float | str]] | None = None,
) -> BacktestResult:
    gap_map = {} if gap_map is None else gap_map
    apply_strategy_config(cfg, gap_map, pullback_half_map=pullback_half_map)
    return aq.run_backtest(
        data=daily,
        strategy=OpenBreak3Strategy,
        symbols=cfg.symbol,
        initial_cash=cfg.initial_cash,
        commission_rate=cfg.commission_rate,
        stamp_tax_rate=cfg.stamp_tax_rate,
        t_plus_one=True,
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

    need_minute = bool(cfg.enable_gap945 or getattr(cfg, "enable_factor2", False))
    minute: pd.DataFrame | None = None
    gap_map: dict[str, Any] = {}
    pullback_half_map: dict[str, dict[str, float | str]] = {}

    if need_minute:
        if verbose:
            print(
                f"拉取 1 分钟线"
                f"{'（945 + 因子2）' if cfg.enable_gap945 and cfg.enable_factor2 else ''}"
                f"{'（945）' if cfg.enable_gap945 and not cfg.enable_factor2 else ''}"
                f"{'（因子2）' if (not cfg.enable_gap945) and cfg.enable_factor2 else ''}"
                f"…"
            )
        minute = load_minute(cfg)

    if cfg.enable_gap945:
        gap_map = build_gap_map(cfg, daily, minute if minute is not None else pd.DataFrame())
        if verbose:
            n_exact = sum(
                1 for v in gap_map.values() if str(v.get("source")) in ("1m", "5m")
            )
            print(
                f"  低开945可触发日: {len(gap_map)} "
                f"（精确={n_exact}，proxy={len(gap_map) - n_exact}）"
            )
    elif verbose:
        print("  低开945规则: 关闭")

    if getattr(cfg, "enable_factor2", False):
        pullback_half_map = build_pullback_half_map(
            daily,
            minute,
            pullback_pct=float(getattr(cfg, "pullback_pct", 0.025) or 0.025),
            tick=cfg.tick,
        )
        if verbose:
            n_1m = sum(1 for v in pullback_half_map.values() if v.get("source") == "1m")
            print(
                f"  因子2可触发日: {len(pullback_half_map)} "
                f"（1m精确={n_1m}，日线近似={len(pullback_half_map) - n_1m}）"
            )

    result = run_open_break_backtest(
        cfg,
        daily,
        gap_map=gap_map,
        pullback_half_map=pullback_half_map,
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
