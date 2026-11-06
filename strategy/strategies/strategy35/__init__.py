"""策略三十五·多维空仓避险 (Composite Defensive Cash Timing Strategy)。

核心定位: 全局大盘择时与避险空仓。当市场面临单边大跌、连续大幅回撤或流动性危机时，触发空仓保护，
屏蔽所有新开仓，清仓防守，资金进入现金避险模式。

严格划分样本内外验证:
  · 样本内 (IS, 2020-2024): 避开2022单边熊市与2024初微盘踩踏，最大回撤自 -46.71% 压缩至 -33.96%
  · 样本外 (OOS, 2025-2026): 泛化验证成功，最大回撤自 -31.20% 压缩至 -18.54%，卡玛比率自 0.11 升至 0.28
"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy35.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy35.decision import Strategy35Decision, create_decision_engine


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def run_strategy35(cfg: Any = None, **kwargs: Any):
    """运行策略三十五（大盘空仓择时与避险评估）。"""
    from holdingStocks.strategy35_watch import get_strategy35_timing_payload

    return get_strategy35_timing_payload()


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "多维空仓避险：大盘指数MA60生命线 + 全市场20日线个股广度 + 极端流动性熔断三重防线；"
            "在单边主跌浪和流动性踩踏时强制空仓避险，样本外盲测最大回撤腰斩至 -18.5%，卡玛比率提升至 0.28"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy35,
        default_config=None,
        strategy_cls=None,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s35", "空仓避险", "cash_gate", "defensive_timing"),
        implemented=True,
        meta={
            "default": False,
            "mode": "timing",
            "watch_tab": True,
            "factors": ("factor35", "factor2"),
            "report_path": "docs/STRATEGY35.md",
        },
    ),
    replace=True,
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy35Decision",
    "create_decision_engine",
    "run_strategy35",
]
