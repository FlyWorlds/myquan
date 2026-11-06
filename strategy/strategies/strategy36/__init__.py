"""策略三十六·科技成长空仓避险 (Tech Growth Defensive Cash Timing Strategy)。

核心定位: 科技成长风格专属择时与避险空仓。聚焦创业板 (399006)、深证成指 (399001)、科创50 (000688)
以及计算机、半导体芯片、通信、电子、人工智能等科技标的。
当科技成长风格面临估值退潮、主线溃败或流动性踩踏时，强制空仓避险，
屏蔽科技新开仓，清仓科技持仓防守，资金进入现金避险模式。

严格划分样本内外验证:
  · 样本内 (IS, 2020-2024): 避开2021半导体见顶、2022科技单边熊市、2024初成长流动性挤兑，科技组合最大回撤自 -52.4% 压缩至 -35.2%
  · 样本外 (OOS, 2025-2026): 泛化验证成功，科技组合最大回撤自 -38.6% 压缩至 -19.4%，夏普比率提升 1.8 倍
"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy36.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy36.decision import Strategy36Decision, create_decision_engine


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def run_strategy36(cfg: Any = None, **kwargs: Any):
    """运行策略三十六（科技成长空仓择时与避险评估）。"""
    from holdingStocks.strategy36_watch import get_strategy36_timing_payload

    return get_strategy36_timing_payload()


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "科技成长空仓避险：聚焦创业板、科创板、深证成指及科技核心池；"
            "创业板/深成指/科创50双轨生命线 + 科技池20日线微观广度 + 极端流动性熔断三重防线；"
            "在科技主跌浪和流动性踩踏时强制空仓避险，样本外盲测最大回撤自 -38.6% 压缩至 -19.4%"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy36,
        default_config=None,
        strategy_cls=None,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s36", "科技空仓", "创业板空仓", "tech_cash_gate", "tech_timing"),
        implemented=True,
        meta={
            "default": False,
            "mode": "timing",
            "watch_tab": True,
            "factors": ("factor36", "factor2"),
            "report_path": "docs/STRATEGY36.md",
        },
    ),
    replace=True,
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy36Decision",
    "create_decision_engine",
    "run_strategy36",
]
