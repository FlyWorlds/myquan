"""策略/因子协议与注册表核心（开闭原则：新增只加模块，不改旧实现）。"""

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import (
    BaseDecisionEngine,
    DecisionEngine,
    engine_from_spec,
    get_decision_engine,
)
from strategy.core.factor_result import DecisionAction, DecisionContext, FactorResult
from strategy.core.protocols import FactorBinding, FactorSpec, StrategySpec, bind_factor
from strategy.core.factor_registry import (
    FACTOR_REGISTRY,
    get_factor,
    list_factors,
    register_factor,
)
from strategy.core.strategy_registry import (
    STRATEGY_REGISTRY,
    get_strategy_spec,
    list_strategy_specs,
    register_strategy,
    resolve_strategy_id,
)

__all__ = [
    "Decision",
    "DecisionAction",
    "DecisionContext",
    "FactorResult",
    "MarketContext",
    "BaseDecisionEngine",
    "DecisionEngine",
    "engine_from_spec",
    "get_decision_engine",
    "FactorBinding",
    "FactorSpec",
    "StrategySpec",
    "bind_factor",
    "FACTOR_REGISTRY",
    "STRATEGY_REGISTRY",
    "get_factor",
    "list_factors",
    "register_factor",
    "get_strategy_spec",
    "list_strategy_specs",
    "register_strategy",
    "resolve_strategy_id",
]
