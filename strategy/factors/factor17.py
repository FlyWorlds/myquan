"""因子17：缠论笔盈亏比（原策略七研究入口，归入缠论因子池）。

用 CZSC 日线笔切段，把因子1 费用后闭环交易按买入笔归因；不产生新的买卖单。
"""

from __future__ import annotations

from typing import Any

from strategy.bi_pl_ratio import analyze_bi_pl_ratio, run_bi_pl_ratio
from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec

FACTOR_ID = "factor17"
FACTOR_NAME = "因子17-缠论笔盈亏比"


def _rules() -> str:
    return """
因子17-缠论笔盈亏比
  · 级别：日线·笔（CZSC；当前库无线段 API 时按笔）
  · 交易对照：因子1 开盘±pct，费用用 strategy.costs 统一口径
  · 记账：闭环收益记入「买入所在笔」；卖点跨笔则卖价平移到买入笔
  · 向上笔让利 = 笔结构涨幅 − 因子1归因复合收益
  · 向下笔防守 = 因子1归因复合收益 − 笔结构跌幅
  · 盈亏比 = 平均盈利 / |平均亏损|（费用后）
  · 角色：评估/对照列（因子16 OOS 可用）；后续可用 bind_factor("factor17") 挂到新策略
  · 不单独下单
研究用途，非投资建议。
""".strip()


def factor17_signal(**kwargs: Any) -> dict[str, Any]:
    """对单标的跑笔归因；kwargs 透传 analyze_bi_pl_ratio。"""
    res = analyze_bi_pl_ratio(**kwargs)
    if hasattr(res, "to_dict"):
        return dict(res.to_dict())
    return {"ok": True}


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "日线笔归因：因子1费用后盈亏按买入笔记账，跨笔卖点平移；"
        "输出盈亏比/让利/防守。可 bind_factor('factor17') 挂到任意策略；"
        "评估因子，不单独产生开平仓指令。"
    ),
    rules_text=_rules(),
    implemented=True,
    signal=factor17_signal,
    meta={
        "kind": "chan_bi_pl",
        "category": "chan",
        "research_only": True,
        "timing": "close_bi_vs_factor1",
        "upstream": ["factor1", "factor8"],
        "hangable": True,
        "cli": "from strategy import run_strategy7; run_strategy7()",
    },
)

register_factor(SPEC, replace=True)

__all__ = [
    "FACTOR_ID",
    "FACTOR_NAME",
    "SPEC",
    "factor17_signal",
    "analyze_bi_pl_ratio",
    "run_bi_pl_ratio",
]
