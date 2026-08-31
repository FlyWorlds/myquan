"""策略十二：因子18 恐慌门控 + 因子1 开盘突破 + 因子2 回撤预警。"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy12.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy12.decision import (
    Strategy12Decision,
    create_decision_engine,
)
from strategy.strategies.strategy12.emotion_gate import panic_halt_by_date


def _print_rules() -> str:
    head = compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)
    extra = """
----- 组合规则 -----
1. 因子18：开盘统计中证1000 低开开盘跌停家数；≥4 记恐慌
2. 恐慌日：禁止新开仓（开盘可观测，无未来函数）；已有仓仍按因子1 止损
3. 平静/正常日：因子1 开盘±2.5%，前日阴/小阳、禁双阳跨日、仅止损、T+1
4. 因子2：回撤加减仓预警，回测不注资
研究用途，非投资建议。
"""
    return head + "\n" + extra.strip()


def run_strategy12(
    cfg: Any = None,
    *,
    show_report: bool = False,
    verbose: bool = True,
    force_daily_refresh: bool = False,
) -> tuple[Any, Any]:
    """单票回测：策略一执行 + 因子18 恐慌日 halt。"""
    from dataclasses import replace

    from strategy.config import KAICHENG
    from strategy.runner import run_open_break
    from strategy.strategies.strategy1 import _attach_factor2_alert_meta

    if cfg is None:
        cfg = KAICHENG
    halt = dict(getattr(cfg, "emotion_halt_by_date", None) or panic_halt_by_date())
    cfg = replace(cfg, emotion_halt_by_date=halt)
    result, daily = run_open_break(
        cfg,
        show_report=show_report,
        verbose=verbose,
        force_daily_refresh=force_daily_refresh,
    )
    _attach_factor2_alert_meta(result, verbose=verbose)
    return result, daily


def _bind() -> StrategySpec:
    from strategy.backtest import OpenBreak3Strategy
    from strategy.config import KAICHENG

    return StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "因子18 恐慌日禁止新开仓 + 因子1 开盘±2.5% 执行 + 因子2 回撤预警；"
            "选股池可另挂；研究组合，非默认盯盘"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy12,
        default_config=KAICHENG,
        strategy_cls=OpenBreak3Strategy,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s12", "emotion_gate", "情绪门控", "策略十二"),
        implemented=True,
        meta={
            "default": False,
            "mode": "emotion_gate",
            "research_only": True,
            "factors": ("factor18", "factor1", "factor2"),
            "backtest_cli": "backtest/strategy12_emotion_gate/run.py",
        },
    )


register_strategy(_bind(), replace=True)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy12Decision",
    "create_decision_engine",
    "run_strategy12",
    "panic_halt_by_date",
]
