"""因子6：组合动量 ETF 轮动（宽基/风格 ETF 截面，非个股）。"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.etf_combo_momentum import (
    DEFAULT_PARAMS,
    DEFAULT_UNIVERSE,
    etf_combo_momentum_rules_text,
    factor6_signal,
)

FACTOR_ID = "factor6"
FACTOR_NAME = "因子6·组合动量ETF轮动"

_RULES = (
    etf_combo_momentum_rules_text()
    + "\n\n"
    + """================================================================================
  组合用法（策略六）
================================================================================
  · 策略六只挂本因子：收盘组合动量 → 次日开盘轮入 TopK / 动量失效空仓
  · 默认参数见 strategy.etf_combo_momentum.DEFAULT_PARAMS
  · 与因子3（个股截面动量/反转）分离：本因子只做场内 ETF 轮动
================================================================================
""".strip()
)

SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "宽基 ETF 组合动量轮动：短窗+长窗 ROC 合成分数，"
        "收盘选 TopK，动量失效空仓；次日开盘执行"
    ),
    rules_text=_RULES,
    implemented=True,
    signal=factor6_signal,
    meta={
        "kind": "etf_combo_momentum",
        "standalone": True,
        "universe": [code for code, _ in DEFAULT_UNIVERSE],
        "default_params": {
            "n": DEFAULT_PARAMS["n"],
            "n2": DEFAULT_PARAMS["n2"],
            "w": DEFAULT_PARAMS["w"],
            "top_k": DEFAULT_PARAMS["top_k"],
            "hold_days": DEFAULT_PARAMS["hold_days"],
            "min_score": DEFAULT_PARAMS["min_score"],
        },
        "research_only": True,
    },
)

register_factor(SPEC, replace=True)


def signal(**kwargs: Any) -> dict[str, Any]:
    return factor6_signal(**kwargs)
