"""策略八：题材联动 — 涨停池同题材共振 + 联动补涨。"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy8.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy8.theme_linkage import run_theme_linkage_backtest


def _print_rules() -> str:
    head = compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)
    extra = """
----- 题材联动规则（v3 · 当日定题材）-----
1. 题材：通达信概念成分（tdx_members_index.json；盯盘随当日涨停实时重算）
2. 因子14：**当日**涨停池 → 同题材同伴数 theme_lu_count ≥ 3
3. 股池：默认 linkage = 热题材内**非当日涨停**联动票（排除龙头）
4. 情绪：T-1 连板梯度（连板≥2、最高板 2～5），与策略三同源
5. 买卖：**当日**因子1 ±阈值突破即买；T+1 止损或收盘清
6. 因子15：默认关闭（--gap-filter 可选启用低开带）
仅供研究，不构成投资建议。
"""
    return head + "\n" + extra.strip()


def run_strategy8(**kwargs: Any) -> dict[str, Any]:
    return run_theme_linkage_backtest(**kwargs)


def _bind() -> StrategySpec:
    return StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "当日涨停定热题材（theme_lu≥3）→ 联动票当日因子1 ±阈值；"
            "T-1 连板梯度门槛；因子15 默认关"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy8,
        default_config=None,
        strategy_cls=None,
        print_rules=_print_rules,
        aliases=("s8", "theme_linkage", "题材联动", "策略八"),
        implemented=True,
        meta={
            "default": False,
            "mode": "theme_linkage",
            "backtest_cli": "backtest/strategy8_theme_linkage/run.py",
            "factors": ("factor14", "factor1"),
        },
    )


register_strategy(_bind())

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "run_strategy8",
    "run_theme_linkage_backtest",
]
