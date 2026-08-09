"""策略一（默认）：因子1（买卖）+ 因子2（回撤补仓叠加）。

调参（开闭，勿改算法本体）：
  · 因子1 阈值/过滤 → open_break.DEFAULT_* 或 bindings / BacktestConfig
  · 因子2 档位/加仓比例 → dd_topup.DEFAULT_* 或 bindings / BacktestConfig.factor2_*
"""

from __future__ import annotations

from typing import Any, Sequence

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy1.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
    strategy1_factor_filter,
)
from strategy.strategies.strategy1.decision import Strategy1Decision, create_decision_engine


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def _factor2_binding():
    for b in FACTOR_BINDINGS:
        if b.enabled and b.factor_id == "factor2":
            return b
    return None


def _resolve_factor2_from_cfg(
    cfg: Any,
    *,
    apply_factor2_overlay: bool = True,
) -> tuple[bool, float, tuple[float, ...]] | None:
    """返回 (enabled, add_pct, levels)；disabled 时返回 None。"""
    from strategy.dd_topup import resolve_topup_params

    binding = _factor2_binding()
    if binding is None:
        return None

    enabled = bool(binding.enabled)
    cfg_en = getattr(cfg, "factor2_enabled", None)
    if cfg_en is not None:
        enabled = bool(cfg_en)
    if not apply_factor2_overlay:
        enabled = False
    if not enabled:
        return None

    add = getattr(cfg, "factor2_add_pct", None)
    if add is None:
        add = binding.params.get("add_pct")
    levels = getattr(cfg, "factor2_levels", None)
    if levels is None:
        levels = binding.params.get("levels")
    pct, lv = resolve_topup_params(
        add_pct=float(add) if add is not None else None,
        levels=levels if levels is not None else None,
    )
    return True, pct, lv


def _apply_factor2_overlay(
    result: Any,
    *,
    initial_cash: float,
    add_pct: float,
    levels: Sequence[float],
    verbose: bool = True,
) -> dict[str, Any] | None:
    """对策略一回测权益叠加因子2；结果挂到 result.factor2_overlay。"""
    eq = getattr(result, "equity_curve", None)
    if eq is None or getattr(eq, "empty", True):
        return None

    from strategy.dd_topup import levels_label
    from strategy.factors.factor2 import run_factor2_on_equity

    nav, events, summary = run_factor2_on_equity(
        eq,
        initial_cash=float(initial_cash),
        add_pct=add_pct,
        levels=levels,
    )
    overlay = {
        "binding": _factor2_binding(),
        "nav": nav,
        "events": events,
        "summary": summary,
        "add_pct": float(add_pct),
        "levels": tuple(levels),
    }
    try:
        result.factor2_overlay = overlay
    except Exception:
        pass

    if verbose and summary:
        print("\n========== 策略一 · 因子2（回撤补仓叠加）==========")
        print(
            f"策略一期末:  {summary.get('base_final', 0):,.2f}  "
            f"(+{summary.get('base_return_pct', 0):.2f}%)"
        )
        print(
            f"叠加因子2后: {summary.get('own_equity', 0):,.2f}  "
            f"(+{summary.get('own_return_pct', 0):.2f}%)"
        )
        print(f"相对多赚:    {summary.get('extra_vs_base', 0):+,.2f}")
        print(f"因子2最大回撤%: {summary.get('max_drawdown_pct', 0):.2f}")
        print(
            f"档位 {levels_label(levels)}  "
            f"每档+{float(add_pct)*100:.0f}%当前权益  事件{len(events)}次"
        )
    return overlay


def run_strategy1(
    cfg: Any = None,
    *,
    show_report: bool = False,
    verbose: bool = True,
    force_daily_refresh: bool = False,
    apply_factor2_overlay: bool = True,
    factor2_add_pct: float | None = None,
    factor2_levels: Sequence[float] | None = None,
) -> tuple[Any, Any]:
    """策略一回测：因子1 交易 +（默认）因子2 权益补仓叠加。

    覆盖因子2 参数（不必改代码）：
      · 调用参数 factor2_add_pct / factor2_levels
      · 或 BacktestConfig.factor2_add_pct / factor2_levels / factor2_enabled
      · 或改 strategy1/bindings.py / dd_topup.DEFAULT_*
    """
    from dataclasses import replace

    from strategy.config import KAICHENG
    from strategy.runner import run_open_break

    if cfg is None:
        cfg = KAICHENG
    if factor2_add_pct is not None or factor2_levels is not None:
        kw: dict[str, Any] = {}
        if factor2_add_pct is not None:
            kw["factor2_add_pct"] = factor2_add_pct
        if factor2_levels is not None:
            kw["factor2_levels"] = tuple(float(x) for x in factor2_levels)
        cfg = replace(cfg, **kw)

    result, daily = run_open_break(
        cfg,
        show_report=show_report,
        verbose=verbose,
        force_daily_refresh=force_daily_refresh,
    )
    resolved = _resolve_factor2_from_cfg(
        cfg, apply_factor2_overlay=apply_factor2_overlay
    )
    if resolved is not None:
        _, pct, lv = resolved
        _apply_factor2_overlay(
            result,
            initial_cash=float(getattr(cfg, "initial_cash", 100_000.0)),
            add_pct=pct,
            levels=lv,
            verbose=verbose,
        )
    return result, daily


def _bind() -> StrategySpec:
    from strategy.backtest import OpenBreak3Strategy
    from strategy.config import KAICHENG

    return StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "默认策略：因子1 开盘±2.5%/阴小阳/禁双阳跨日≥5%/仅止损"
            " + 因子2 回撤阶梯补仓（叠权益；档位/比例可配）"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy1,
        default_config=KAICHENG,
        strategy_cls=OpenBreak3Strategy,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("open_break3", "s1", "策略一"),
        implemented=True,
        meta={
            "default": True,
            "legacy_id": "open_break3",
            "factors": ("factor1", "factor2"),
            "factor2_overlay": True,
        },
    )


register_strategy(_bind())

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "strategy1_factor_filter",
    "Strategy1Decision",
    "create_decision_engine",
    "run_strategy1",
    "_apply_factor2_overlay",
]
