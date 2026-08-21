"""策略二：CZSC 缠论多级别选股与事件回测。"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy2.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
    strict_yin_filter,
)
from strategy.strategies.strategy2.decision import Strategy2Decision, create_decision_engine
from strategy.strategies.strategy2.portfolio import run_chan_portfolio


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def _run(cfg: Any = None, **kwargs: Any):
    overrides = dict(cfg) if isinstance(cfg, dict) else {}
    overrides.update(kwargs)
    return run_chan_portfolio(
        panel=overrides.get("panel"),
        panel_path=overrides.get("panel_path"),
        factor_column=overrides.get("factor_column"),
        start=overrides.get("start"),
        end=overrides.get("end"),
        fee_rate=overrides.get("fee_rate"),
    )


run_strategy2 = _run


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description="日线缠论选股：30分钟小转大一买/二买开仓，日线二卖或三卖退出",
        factor_bindings=FACTOR_BINDINGS,
        run=_run,
        default_config={
            "base_freq": "日线",
            "confirm_freq": "30分钟",
            "universe": "zz500_1000",
            "top_k": 10,
            "entry": "xiaozhuan_buy1_then_buy2",
            "exit": ("sell2", "sell3"),
        },
        strategy_cls=None,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s2", "chan", "缠论", "缠论策略二"),
        implemented=True,
        meta={"default": False, "mode": "portfolio", "standalone_factor": "factor8"},
    ),
    replace=True,
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "strict_yin_filter",
    "Strategy2Decision",
    "create_decision_engine",
    "run_chan_portfolio",
    "run_strategy2",
]
