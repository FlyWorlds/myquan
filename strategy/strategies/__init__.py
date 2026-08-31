"""策略模块（可插拔）。

每个策略包分层：
  · bindings.py  — 策略层：因子绑定 / 参数 / 过滤器
  · decision.py  — 决策层：MarketContext → Decision（buy/sell/hold）
  · __init__.py  — 注册 StrategySpec（含 decision_factory / run）

  strategy1 — 援军战法（默认）：因子1（买卖）+ 因子2（回撤预警）
  strategy2 — 缠论选股：日线交易，30分钟小转大一买/二买，日线二/三卖退出
  strategy3 — 首板晋级：昨日首板 → 次日因子1 开盘突破
  strategy4 — 因子1 + 因子4 + 20%昨高止盈 + 因子10 周频动量选股（旧 strategy9）
  strategy5 — 因子11 两段近高（3日动量→5日近高 Top5）等权持有（旧 strategy10）
  strategy6 — 因子12 反转池近高 Top5 等权持有（研究候选）
  strategy7 — CLI 兼容：缠论笔盈亏比已归因子17（Web 不展示）
  strategy8 — 题材联动：涨停池同题材共振 + 联动补涨（因子14 + 因子1）
  strategy9 — 低开跌停情绪：中证1000 低开开盘跌停家数 vs 大盘当日涨跌（研究）
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
from strategy.strategies import strategy9 as _s9e  # noqa: F401
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
