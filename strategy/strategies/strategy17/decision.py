"""策略十七·紫阳真君 · 决策层。"""

from __future__ import annotations

from strategy.strategies._factor26_decision import Factor26Decision
from strategy.strategies.strategy17.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy17Decision(Factor26Decision):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME


def create_decision_engine(spec=None) -> Strategy17Decision:  # noqa: ANN001
    del spec
    return Strategy17Decision(FACTOR_BINDINGS)
