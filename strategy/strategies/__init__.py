"""策略模块（可插拔）。

每个策略包分层：
  · bindings.py  — 策略层：因子绑定 / 参数 / 过滤器
  · decision.py  — 决策层：MarketContext → Decision（buy/sell/hold）
  · __init__.py  — 注册 StrategySpec（含 decision_factory / run）

  strategy1 — 援军战法（默认）：因子1（买卖）+ 因子2（回撤预警）
  strategy2 — 缠论选股：日线交易，30分钟小转大一买/二买，日线二/三卖退出
  strategy3/4 — 骨架或动量/建池变体
  strategy5 — 动量因子组合（因子3 · 中证1000截面）
  strategy6 — 因子6 组合动量 ETF 轮动
  strategy7 — 因子5 Serenity 公开帖驱动的主题事件策略
  strategy8 — 因子7 行业 ETF 双动量月频 Top3
"""

# 策略注册前先确保因子已注册（多策略共用因子）
import strategy.factors  # noqa: F401

from strategy.strategies import strategy1 as _s1  # noqa: F401
from strategy.strategies import strategy2 as _s2  # noqa: F401
from strategy.strategies import strategy3 as _s3  # noqa: F401
from strategy.strategies import strategy4 as _s4  # noqa: F401
from strategy.strategies import strategy5 as _s5  # noqa: F401
from strategy.strategies import strategy6 as _s6  # noqa: F401
from strategy.strategies import strategy7 as _s7  # noqa: F401
from strategy.strategies import strategy8 as _s8  # noqa: F401
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
