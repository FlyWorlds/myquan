"""策略四 · 决策层：沿用因子1 买卖点。"""

from __future__ import annotations

from strategy.strategies.strategy1.decision import Strategy1Decision
from strategy.core.protocols import StrategySpec
from strategy.strategies.strategy4.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy4Decision(Strategy1Decision):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME


Strategy9Decision = Strategy4Decision


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy4Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy4Decision(bindings=bindings)
