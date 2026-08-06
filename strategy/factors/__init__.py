"""因子模块（可插拔）。

导入本包即完成注册：
  · factor1 — 开盘±pct（默认 ±2.5%），现行唯一生效因子
  · factor2 / factor3 — 占位，待实现
"""

from strategy.factors import factor1 as _factor1  # noqa: F401
from strategy.factors import factor2 as _factor2  # noqa: F401
from strategy.factors import factor3 as _factor3  # noqa: F401
from strategy.core.factor_registry import FACTOR_REGISTRY, get_factor, list_factors

__all__ = ["FACTOR_REGISTRY", "get_factor", "list_factors"]
