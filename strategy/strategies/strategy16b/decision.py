"""策略十六B·条件选股 · 决策层：复用策略16买卖绑定。"""

from __future__ import annotations

from strategy.strategies._factor26_decision import Factor26Decision
from strategy.strategies.strategy16b.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy16BDecision(Factor26Decision):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME


def create_decision_engine(spec=None) -> Strategy16BDecision:  # noqa: ANN001
    return Strategy16BDecision(FACTOR_BINDINGS)

