"""策略六：因子6 组合动量 ETF 轮动。"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.etf_combo_momentum import DEFAULT_PARAMS, run_etf_combo_momentum
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy6.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME
from strategy.strategies.strategy6.decision import Strategy6Decision, create_decision_engine
from strategy.strategies.strategy6.portfolio import run_f3_select_f1_stop_portfolio


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def run_strategy6(cfg: Any = None, **kwargs: Any):
    """跑因子6 ETF 组合动量轮动；cfg 可传 dict 覆盖参数。"""
    overrides: dict[str, Any] = dict(DEFAULT_PARAMS)
    if isinstance(cfg, dict):
        overrides.update(cfg)
    overrides.update(kwargs)
    return run_etf_combo_momentum(
        n=overrides.get("n"),
        n2=overrides.get("n2"),
        w=overrides.get("w"),
        top_k=overrides.get("top_k"),
        hold_days=overrides.get("hold_days"),
        min_score=overrides.get("min_score"),
        defensive=overrides.get("defensive"),
        start=overrides.get("start"),
        end=overrides.get("end"),
        warm_start=overrides.get("warm_start"),
        universe=overrides.get("universe"),
        refresh=bool(overrides.get("refresh", False)),
        initial_cash=overrides.get("initial_cash"),
        verbose=bool(overrides.get("verbose", True)),
        dailies=overrides.get("dailies"),
    )


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "因子6宽基ETF组合动量轮动："
            f"ROC({DEFAULT_PARAMS['n']})+{DEFAULT_PARAMS['w']:g}×ROC({DEFAULT_PARAMS['n2']}) "
            f"Top{DEFAULT_PARAMS['top_k']}/每{DEFAULT_PARAMS['hold_days']}日再平衡；"
            "动量失效空仓"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy6,
        default_config=dict(DEFAULT_PARAMS),
        strategy_cls=None,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s6", "factor6", "etf_combo_momentum", "组合动量ETF轮动"),
        implemented=True,
        meta={
            "default": False,
            "standalone_factor": "factor6",
            "mode": "etf_rotation",
            "portfolio": dict(DEFAULT_PARAMS),
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
    "run_strategy6",
    "run_etf_combo_momentum",
    "run_f3_select_f1_stop_portfolio",
]
