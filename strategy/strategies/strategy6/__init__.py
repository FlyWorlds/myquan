"""策略六：因子3截面选股 + 因子1开盘止损。"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.open_break import DEFAULT_PCT
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy5.portfolio import PORTFOLIO_DEFAULTS
from strategy.strategies.strategy6.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME
from strategy.strategies.strategy6.decision import Strategy6Decision, create_decision_engine
from strategy.strategies.strategy6.portfolio import run_f3_select_f1_stop_portfolio


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def _run(cfg: Any = None, **kwargs: Any):
    """跑因子3选股 + 因子1止损组合；cfg 可传 dict 覆盖参数。"""
    overrides: dict[str, Any] = dict(PORTFOLIO_DEFAULTS)
    overrides["stop_pct"] = DEFAULT_PCT
    if isinstance(cfg, dict):
        overrides.update(cfg)
    overrides.update(kwargs)
    return run_f3_select_f1_stop_portfolio(
        kind=overrides.get("kind"),
        n=overrides.get("n"),
        top_k=overrides.get("top_k"),
        hold_days=overrides.get("hold_days"),
        min_score=overrides.get("min_score"),
        ma_filter=overrides.get("ma_filter"),
        stop_pct=overrides.get("stop_pct"),
        start=overrides.get("start"),
        end=overrides.get("end"),
        warm_start=overrides.get("warm_start"),
        universe=overrides.get("universe"),
        refresh=bool(overrides.get("refresh", False)),
        verbose=bool(overrides.get("verbose", True)),
    )


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "因子3截面选股买入 + 因子1开盘止损卖出；"
            f"默认 {PORTFOLIO_DEFAULTS['kind']}(n={PORTFOLIO_DEFAULTS['n']}) "
            f"Top{PORTFOLIO_DEFAULTS['top_k']}/最长持有{PORTFOLIO_DEFAULTS['hold_days']}日/"
            f"止损-{DEFAULT_PCT*100:.1f}%"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=_run,
        default_config={**dict(PORTFOLIO_DEFAULTS), "stop_pct": DEFAULT_PCT},
        strategy_cls=None,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s6", "f3_select_f1_stop", "因子3选股因子1止损"),
        implemented=True,
        meta={
            "default": False,
            "select_factor": "factor3",
            "stop_factor": "factor1",
            "mode": "portfolio",
            "portfolio": {**dict(PORTFOLIO_DEFAULTS), "stop_pct": DEFAULT_PCT},
        },
    ),
    replace=True,
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy6Decision",
    "create_decision_engine",
    "run_f3_select_f1_stop_portfolio",
]
