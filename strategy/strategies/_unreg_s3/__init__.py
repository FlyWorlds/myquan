"""策略三：挂因子3（动量因子组合）。"""

from __future__ import annotations

from typing import Any

from strategy.strategies._common import compose_rules
from strategy.strategies._unreg_s3.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME
from strategy.strategies._unreg_s3.decision import Strategy3Decision, create_decision_engine
from strategy.strategies._unreg_s5.portfolio import PORTFOLIO_DEFAULTS, run_momentum_portfolio


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def _run(cfg: Any = None, **kwargs: Any):
    """默认跑截面组合；cfg 可传 dict 覆盖 kind/n/top_k/hold_days 等。"""
    overrides: dict[str, Any] = dict(PORTFOLIO_DEFAULTS)
    if isinstance(cfg, dict):
        overrides.update(cfg)
    overrides.update(kwargs)
    return run_momentum_portfolio(
        kind=overrides.get("kind"),
        n=overrides.get("n"),
        top_k=overrides.get("top_k"),
        hold_days=overrides.get("hold_days"),
        min_score=overrides.get("min_score"),
        ma_filter=overrides.get("ma_filter"),
        start=overrides.get("start"),
        end=overrides.get("end"),
        warm_start=overrides.get("warm_start"),
        refresh=bool(overrides.get("refresh", False)),
        verbose=bool(overrides.get("verbose", True)),
    )


__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy3Decision",
    "create_decision_engine",
]
