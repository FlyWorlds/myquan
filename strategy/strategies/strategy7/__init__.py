"""策略七：因子1 + 因子4 牛市持股修复（针对因子1 跑输平权持有的阶段）。

默认组合宇宙（独立等权）：
  · 凯盛科技 600552 · 因子1 ±2.5% + 逐票 F4
  · 天通股份 600330 · 因子1 ±3.0% + 逐票 F4
  · 科创综指ETF 589680 · 因子1 买2.5%/止3.5% + F4(roc_ma60·放宽2x) · T+1
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy7.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy7.decision import Strategy7Decision, create_decision_engine

# 策略七默认三票宇宙（顺序固定，便于组合等权）
S7_UNIVERSE_IDS = ("kaicheng", "tiantong", "kczz")


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def _factor4_params_from_bindings() -> dict[str, Any]:
    for b in FACTOR_BINDINGS:
        if b.factor_id == "factor4" and b.enabled:
            p = dict(b.params)
            kind = str(p.pop("kind", "roc_ma"))
            return {"kind": kind, "params": p}
    return {"kind": "roc_ma", "params": {}}


def default_s7_universe() -> list[Any]:
    """返回策略七默认三票 BacktestConfig（未套 F4；由 run_strategy7 按 mode 套用）。"""
    from strategy.config import KAICHENG, KCZZ_ETF, TIANTONG

    return [KAICHENG, TIANTONG, KCZZ_ETF]


def run_strategy7(
    cfg: Any = None,
    *,
    show_report: bool = False,
    verbose: bool = True,
    force_daily_refresh: bool = False,
    mode: str = "unified",
    bull_entry: bool = False,
    skip_f1_entry_in_bull: bool = False,
    stop_widen_mult: float | None = None,
) -> tuple[Any, Any]:
    """策略七回测：因子1 + 因子4 牛市持股修复。

    mode:
      · unified — 统一 roc_ma60 + 止损放宽2倍
      · per_symbol — 逐票优化 F4（凯盛/天通/科创综指各有推荐）；非牛市仅F1
      · binding — 仅用 bindings 默认
    """
    from strategy.config import KAICHENG, resolve_factor4_repair
    from strategy.runner import run_open_break

    if cfg is None:
        cfg = KAICHENG

    if mode == "per_symbol":
        cfg = resolve_factor4_repair(cfg)
    elif mode == "unified":
        from strategy.config import FACTOR4_REPAIR_UNIFIED

        cfg = replace(cfg, **FACTOR4_REPAIR_UNIFIED)  # type: ignore[arg-type]
    else:
        f4 = _factor4_params_from_bindings()
        cfg = replace(
            cfg,
            factor4_enabled=True,
            factor4_kind=f4["kind"],
            factor4_params=dict(f4["params"]),
        )

    if bull_entry:
        cfg = replace(cfg, factor4_bull_entry=True)
    if skip_f1_entry_in_bull:
        cfg = replace(cfg, factor4_skip_f1_entry_in_bull=True)
    if stop_widen_mult is not None:
        cfg = replace(cfg, factor4_stop_widen_mult=float(stop_widen_mult))

    return run_open_break(
        cfg,
        show_report=show_report,
        verbose=verbose,
        force_daily_refresh=force_daily_refresh,
    )


def resolve_strategy7_config(
    cfg: Any,
    *,
    mode: str = "per_symbol",
    bull_entry: bool = False,
    skip_f1_entry_in_bull: bool = False,
    stop_widen_mult: float | None = None,
) -> Any:
    """套用策略七 mode / 开关，返回最终回测配置（不跑回测）。"""
    from strategy.config import resolve_factor4_repair

    if mode == "per_symbol":
        cfg = resolve_factor4_repair(cfg)
    elif mode == "unified":
        from strategy.config import FACTOR4_REPAIR_UNIFIED

        cfg = replace(cfg, **FACTOR4_REPAIR_UNIFIED)  # type: ignore[arg-type]
    else:
        f4 = _factor4_params_from_bindings()
        cfg = replace(
            cfg,
            factor4_enabled=True,
            factor4_kind=f4["kind"],
            factor4_params=dict(f4["params"]),
        )
    if bull_entry:
        cfg = replace(cfg, factor4_bull_entry=True)
    if skip_f1_entry_in_bull:
        cfg = replace(cfg, factor4_skip_f1_entry_in_bull=True)
    if stop_widen_mult is not None:
        cfg = replace(cfg, factor4_stop_widen_mult=float(stop_widen_mult))
    return cfg


def run_strategy7_universe(
    configs: list[Any] | None = None,
    *,
    mode: str = "per_symbol",
    show_report: bool = False,
    verbose: bool = False,
    force_daily_refresh: bool = False,
) -> list[tuple[Any, Any, Any]]:
    """对宇宙内每票跑策略七，返回 [(resolved_cfg, result, daily), ...]。"""
    from strategy.runner import run_open_break

    cfgs = list(configs) if configs is not None else default_s7_universe()
    out: list[tuple[Any, Any, Any]] = []
    for raw in cfgs:
        cfg = resolve_strategy7_config(raw, mode=mode)
        r, d = run_open_break(
            cfg,
            show_report=show_report,
            verbose=verbose,
            force_daily_refresh=force_daily_refresh,
        )
        out.append((cfg, r, d))
    return out


def _bind() -> StrategySpec:
    from strategy.backtest import OpenBreak3Strategy
    from strategy.config import KAICHENG

    return StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "因子1 开盘突破 + 因子4 牛市持股；"
            "默认宇宙=凯盛/天通/科创综指ETF，独立等权"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy7,
        default_config=KAICHENG,
        strategy_cls=OpenBreak3Strategy,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s7", "f1_f4_bull", "策略七"),
        implemented=True,
        meta={
            "factors": ("factor1", "factor4"),
            "factor4_overlay": "stop_suppress",
            "universe": S7_UNIVERSE_IDS,
        },
    )


register_strategy(_bind())

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "S7_UNIVERSE_IDS",
    "Strategy7Decision",
    "create_decision_engine",
    "default_s7_universe",
    "resolve_strategy7_config",
    "run_strategy7",
    "run_strategy7_universe",
]
