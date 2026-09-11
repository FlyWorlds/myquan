"""策略十六·核心龙头 · 决策层：绑定本策略 factor26/22，内核与策略一解耦。"""

from __future__ import annotations

from strategy.strategies._factor26_decision import Factor26Decision
from strategy.strategies.strategy16.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy16Decision(Factor26Decision):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME


def create_decision_engine(spec=None) -> Strategy16Decision:  # noqa: ANN001
    del spec
    return Strategy16Decision(FACTOR_BINDINGS)
