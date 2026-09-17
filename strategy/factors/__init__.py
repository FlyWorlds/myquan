"""因子模块（可插拔）。

导入本包即完成注册：
  · factor1 — 开盘±pct（默认 ±2.5%）；策略一已改挂 factor26，本因子仍可复用
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
  · factor13a — 策略1质量带契合选股（factor13_fit）
  · factor13b — 熊市盾牌 thr* Top3（factor13_bear_shield，🔒锁定）
  · factor13 — 兼容别名 → factor13a（见 docs/FACTOR13.md）
  · factor14 — 题材共振（同题材涨停同伴数 theme_lu_count，策略八选股）
  · factor15 — 题材晋级低开（晋级日 gap ∈ [-4.5%, -0.3%]，策略八补涨过滤）
  · factor16 — 概念龙头评分（F13质量带 + 因子1 OOS + 缠论笔；见 docs/FACTOR16.md）
  · factor17 — 缠论笔盈亏比（原策略七研究入口，评估因子）
  · factor18 — 低开跌停情绪（中证1000 低开开盘跌停家数；策略十二择时）
  · factor19 — 低开反包（压力日 gap 带；策略十二旧假设，未过关）
  · factor20 — 跌停次日开板（昨收跌停今开未封；已否决）
  · factor21 — 涨停次日低开（昨收涨停今低开；策略十二选股）
  · factor22 — 收盘动量（止损后再买；策略一研究；策略十六默认关）
  · factor23 — 最高连板止盈（弱板早止盈 / 3～4 板 10% 减半 / 高潮放宽）
  · factor24 — 连板梯度情绪（定止盈目标 + 是否启用因子22）
  · factor25 — 30m 震荡减磨损（确认止损 + 动态半仓止盈 + 卖飞回补）
  · factor26 — 浮盈回落一半止盈（买同开盘突破；卖=持仓最高浮盈回落一半；策略一主因子）
  · factor27 — 核心龙头（通达信活跃概念偏高 → 概念内龙头；滚动近3个月冻结；策略十六宇宙）
  · factor28 — 紫阳真君（国泰海通/国泰君安武汉紫阳东路近3个月龙虎榜成交池；策略十七宇宙）
  · cf1 — 流动性门控反转（Amihud 软门 × 短期反转）
  分类见 strategy.factors.categories
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
from strategy.factors import factor13a as _factor13a  # noqa: F401
from strategy.factors import factor13b as _factor13b  # noqa: F401
from strategy.factors import factor13 as _factor13  # noqa: F401
from strategy.factors import factor14 as _factor14  # noqa: F401
from strategy.factors import factor15 as _factor15  # noqa: F401
from strategy.factors import factor16 as _factor16  # noqa: F401
from strategy.factors import factor17 as _factor17  # noqa: F401
from strategy.factors import factor18 as _factor18  # noqa: F401
from strategy.factors import factor19 as _factor19  # noqa: F401
from strategy.factors import factor20 as _factor20  # noqa: F401
from strategy.factors import factor21 as _factor21  # noqa: F401
from strategy.factors import factor22 as _factor22  # noqa: F401
from strategy.factors import factor23 as _factor23  # noqa: F401
from strategy.factors import factor24 as _factor24  # noqa: F401
from strategy.factors import factor25 as _factor25  # noqa: F401
from strategy.factors import factor26 as _factor26  # noqa: F401
from strategy.factors import factor27 as _factor27  # noqa: F401
from strategy.factors import factor28 as _factor28  # noqa: F401
from strategy.factors import factor_cf1 as _factor_cf1  # noqa: F401
from strategy.core.factor_registry import FACTOR_REGISTRY, get_factor, list_factors
from strategy.factors.categories import list_category_catalog

__all__ = ["FACTOR_REGISTRY", "get_factor", "list_factors", "list_category_catalog"]
