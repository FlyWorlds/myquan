"""因子模块（可插拔）。

导入本包即完成注册：
  · factor1 — 开盘±pct（默认 ±2.5%），策略一买卖真源
  · factor2 — 回撤阶梯补仓（叠在权益曲线上的资金管理）
  · factor3 — 动量（策略五·动量因子组合 / 亦可单票时序）
  · factor4 — 牛市持股 regime
  · factor5 — Serenity 公开前瞻主题 → A 股研究候选池
  · factor6 — 组合动量 ETF 轮动
  · factor7 — 行业 ETF 普通动量 + 改进残差动量
  · factor8 — CZSC 缠论结构与一/二/三类买卖点
  · factor9 — 日线多空动能（追涨杀跌，选股门控）
  · factor10 — 价格选股（周频冻结近高/趋势/动量）
  · factor11 — 两段近高选股（3日动量 Top20 → 贴近5日高点 Top5）
  · factor12 — 20日反转池 → 近5日高 Top5（研究候选，不替换 factor11）
  · factor13 — 策略1契合选股（质量带 factor13_fit / 熊盾 factor13_bear_shield，见 docs/FACTOR13.md）
  · cf1 — 流动性门控反转（Amihud 软门 × 短期反转）
"""

from strategy.factors import factor1 as _factor1  # noqa: F401
from strategy.factors import factor2 as _factor2  # noqa: F401
from strategy.factors import factor3 as _factor3  # noqa: F401
from strategy.factors import factor4 as _factor4  # noqa: F401
from strategy.factors import factor5 as _factor5  # noqa: F401
from strategy.factors import factor6 as _factor6  # noqa: F401
from strategy.factors import factor7 as _factor7  # noqa: F401
from strategy.factors import factor8 as _factor8  # noqa: F401
from strategy.factors import factor9 as _factor9  # noqa: F401
from strategy.factors import factor10 as _factor10  # noqa: F401
from strategy.factors import factor11 as _factor11  # noqa: F401
from strategy.factors import factor12 as _factor12  # noqa: F401
from strategy.factors import factor13 as _factor13  # noqa: F401
from strategy.factors import factor_cf1 as _factor_cf1  # noqa: F401
from strategy.core.factor_registry import FACTOR_REGISTRY, get_factor, list_factors

__all__ = ["FACTOR_REGISTRY", "get_factor", "list_factors"]
