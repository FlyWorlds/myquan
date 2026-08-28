"""策略十二：竞价一字联动选股。"""

from __future__ import annotations

from typing import Any

from strategy.auction_yizi_linkage import (
    AuctionYiziLinkageResult,
    DEFAULT_PARAMS,
    run_auction_yizi_linkage,
)
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


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def run_strategy12(cfg: Any = None, **kwargs: Any) -> AuctionYiziLinkageResult:
    """竞价一字联动：题材锚 + 高开联动 TopK 等权持有。研究回测，不构成投资建议。"""
    overrides: dict[str, Any] = dict(DEFAULT_PARAMS)
    if isinstance(cfg, dict):
        overrides.update(cfg)
    overrides.update(kwargs)
    return run_auction_yizi_linkage(**overrides)


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "因子14：当日竞价/开盘一字为题材锚，同概念内选高开联动标的 TopK，"
            "T 开盘等权持有"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy12,
        default_config=dict(DEFAULT_PARAMS),
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=(
            "s12",
            "auction_yizi",
            "yizi_linkage",
            "竞价一字联动",
            "策略十二",
        ),
        implemented=True,
        meta={
            "default": False,
            "standalone_factor": "factor14",
            "mode": "daily_linkage_hold",
            "research_only": True,
        },
    ),
    replace=True,
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy12Decision",
    "create_decision_engine",
    "run_strategy12",
    "run_auction_yizi_linkage",
    "AuctionYiziLinkageResult",
]
