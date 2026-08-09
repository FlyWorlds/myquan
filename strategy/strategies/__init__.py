"""策略模块（可插拔）。

每个策略包分层：
  · bindings.py  — 策略层：因子绑定 / 参数 / 过滤器
  · decision.py  — 决策层：MarketContext → Decision（buy/sell/hold）
  · __init__.py  — 注册 StrategySpec（含 decision_factory / run）

  strategy1 — 默认生效：因子1（买卖）+ 因子2（回撤补仓叠加）
  strategy2/3/4 — 骨架（同因子不同 params；回测 runner 待接）
  strategy5 — 单因子4·动量
"""

# 策略注册前先确保因子已注册（多策略共用因子）
import strategy.factors  # noqa: F401

from strategy.strategies import strategy1 as _s1  # noqa: F401
from strategy.strategies import strategy2 as _s2  # noqa: F401
from strategy.strategies import strategy3 as _s3  # noqa: F401
from strategy.strategies import strategy4 as _s4  # noqa: F401
from strategy.strategies import strategy5 as _s5  # noqa: F401
from strategy.core.strategy_registry import (
    STRATEGY_REGISTRY,
    get_strategy_spec,
    list_strategy_specs,
)

__all__ = [
    "STRATEGY_REGISTRY",
    "get_strategy_spec",
    "list_strategy_specs",
]
