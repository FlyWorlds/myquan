"""策略十六·核心龙头 · 决策层：复用策略一（因子26/22）。"""

from __future__ import annotations

from strategy.strategies.strategy1.decision import Strategy1Decision
from strategy.strategies.strategy16.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy16Decision(Strategy1Decision):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME


def create_decision_engine(spec=None) -> Strategy16Decision:  # noqa: ANN001
    del spec
    return Strategy16Decision(FACTOR_BINDINGS)
