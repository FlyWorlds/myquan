"""援军战法 · 决策层：绑定本策略 factor26/22，内核在 _factor26_decision。"""

from __future__ import annotations

from strategy.strategies._factor26_decision import Factor26Decision
from strategy.strategies.strategy1.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy1Decision(Factor26Decision):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME


def create_decision_engine(spec=None) -> Strategy1Decision:  # noqa: ANN001
    del spec
    return Strategy1Decision(FACTOR_BINDINGS)
