"""策略十一：缠论笔算盈亏比。

用 CZSC 日线笔切分行情，把因子1（开盘突破）费用后闭环交易按买入笔归因；
卖点落在另一笔时，卖价差价平移记入买入笔，并输出盈亏比 / 让利 / 防守。
"""

from __future__ import annotations

from typing import Any

from strategy.bi_pl_ratio import BiPlRatioResult, analyze_bi_pl_ratio, run_bi_pl_ratio
from strategy.config import TIANTONG
from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy11.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy11.decision import Strategy11Decision, create_decision_engine


def _print_rules() -> str:
    head = compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)
    extra = """
----- 笔归因规则 -----
1. 级别：日线·笔（CZSC；当前库无线段 API 时按笔）
2. 交易：因子1 开盘±pct，费用用 strategy.costs 统一口径
3. 记账：闭环收益记入「买入所在笔」；卖点跨笔则卖价平移到买入笔
4. 向上笔让利 = 笔结构涨幅 − 因子1归因复合收益
5. 向下笔防守 = 因子1归因复合收益 − 笔结构跌幅
6. 盈亏比 = 平均盈利 / |平均亏损|（费用后）
仅供研究，不构成投资建议。
"""
    return head + "\n" + extra.strip()


def run_strategy11(cfg: Any = None, **kwargs: Any) -> BiPlRatioResult:
    """默认对天通股份跑笔盈亏比报告；可用 kwargs 覆盖 symbol/区间/阈值。"""
    return run_bi_pl_ratio(cfg if cfg is not None else TIANTONG, **kwargs)


def _bind() -> StrategySpec:
    return StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "日线笔归因：因子1开盘突破费用后盈亏按买入笔记账，"
            "跨笔卖点平移，输出盈亏比/让利/防守"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy11,
        default_config=TIANTONG,
        strategy_cls=None,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=(
            "s11",
            "bi_pl",
            "bi_pl_ratio",
            "缠论笔算盈亏比",
            "笔盈亏比",
        ),
        implemented=True,
        meta={
            "default": False,
            "mode": "research_attribution",
            "standalone_factor": "factor1",
            "structure": "czsc_bi",
        },
    )


register_strategy(_bind())

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy11Decision",
    "create_decision_engine",
    "analyze_bi_pl_ratio",
    "run_bi_pl_ratio",
    "run_strategy11",
    "BiPlRatioResult",
]
