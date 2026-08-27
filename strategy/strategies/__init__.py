"""策略模块（可插拔）。

每个策略包分层：
  · bindings.py  — 策略层：因子绑定 / 参数 / 过滤器
  · decision.py  — 决策层：MarketContext → Decision（buy/sell/hold）
  · __init__.py  — 注册 StrategySpec（含 decision_factory / run）

  strategy1 — 援军战法（默认）：因子1（买卖）+ 因子2（回撤预警）
  strategy2 — 缠论选股：日线交易，30分钟小转大一买/二买，日线二/三卖退出
  strategy3 — 因子5 Serenity 公开帖驱动的主题事件策略（旧 strategy7）
  strategy4 — 因子1 + 因子4 + 20%昨高止盈 + 因子10 周频动量选股（旧 strategy9）
  strategy5 — 因子11 两段近高（3日动量→5日近高 Top5）等权持有（旧 strategy10）
  strategy6 — 因子12 反转池近高 Top5 等权持有（研究候选）
  strategy11 — 缠论笔算盈亏比：日线笔归因因子1费用后盈亏比/让利/防守
"""

# 策略注册前先确保因子已注册（多策略共用因子）
import strategy.factors  # noqa: F401

from strategy.strategies import strategy1 as _s1  # noqa: F401
from strategy.strategies import strategy2 as _s2  # noqa: F401
from strategy.strategies import strategy3 as _s3  # noqa: F401
from strategy.strategies import strategy4 as _s4  # noqa: F401
from strategy.strategies import strategy5 as _s5  # noqa: F401
from strategy.strategies import strategy6 as _s6  # noqa: F401
from strategy.strategies import strategy11 as _s11  # noqa: F401
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
