"""策略五：动量因子组合（中证1000截面 TopK）。"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy5.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME
from strategy.strategies.strategy5.decision import Strategy5Decision, create_decision_engine
from strategy.strategies.strategy5.portfolio import PORTFOLIO_DEFAULTS, run_momentum_portfolio


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


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "动量因子组合：中证1000主板截面选股；"
            f"默认 {PORTFOLIO_DEFAULTS['kind']}(n={PORTFOLIO_DEFAULTS['n']}) "
            f"Top{PORTFOLIO_DEFAULTS['top_k']}/持有{PORTFOLIO_DEFAULTS['hold_days']}日"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=_run,
        default_config=dict(PORTFOLIO_DEFAULTS),
        strategy_cls=None,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s5", "momentum", "factor3", "动量因子组合"),
        implemented=True,
        meta={
            "default": False,
            "standalone_factor": "factor3",
            "mode": "portfolio",
            "portfolio": dict(PORTFOLIO_DEFAULTS),
        },
    ),
    replace=True,
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "PORTFOLIO_DEFAULTS",
    "Strategy5Decision",
    "create_decision_engine",
    "run_momentum_portfolio",
]
