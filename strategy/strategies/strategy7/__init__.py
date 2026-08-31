"""策略七 · CLI 包装：缠论笔盈亏比已归因子17。

保留 run_strategy7 / 旧号 strategy11 以便脚本不改；Web 策略栏不再展示。
"""

from __future__ import annotations

from typing import Any

from strategy.bi_pl_ratio import BiPlRatioResult, analyze_bi_pl_ratio, run_bi_pl_ratio
from strategy.config import TIANTONG
from strategy.core.protocols import StrategySpec, bind_factor
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy7.decision import Strategy7Decision, create_decision_engine

STRATEGY_ID = "strategy7"
STRATEGY_NAME = "策略七·缠论笔算盈亏比"

FACTOR_BINDINGS = (
    bind_factor(
        "factor17",
        label="缠论笔盈亏比",
        role="custom",
        filter_desc="评估因子：因子1 费用后盈亏按买入笔记账，不单独下单",
    ),
)


def _print_rules() -> str:
    head = compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)
    extra = """
----- 说明 -----
缠论笔盈亏比已注册为 **因子17**，本入口仅保留 CLI 兼容。
Web 请到「因子说明 → 缠论」。
"""
    return head + "\n" + extra.strip()


def run_strategy7(cfg: Any = None, **kwargs: Any) -> BiPlRatioResult:
    """默认对天通股份跑笔盈亏比报告；可用 kwargs 覆盖 symbol/区间/阈值。"""
    return run_bi_pl_ratio(cfg if cfg is not None else TIANTONG, **kwargs)


run_strategy11 = run_strategy7


def _bind() -> StrategySpec:
    return StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description="兼容 CLI：等同因子17-缠论笔盈亏比；Web 策略栏不展示",
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy7,
        default_config=TIANTONG,
        strategy_cls=None,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=(
            "s7",
            "s11",
            "strategy11",
            "bi_pl",
            "bi_pl_ratio",
            "缠论笔算盈亏比",
            "笔盈亏比",
            "策略七",
            "factor17",
        ),
        implemented=True,
        meta={
            "default": False,
            "mode": "research_attribution",
            "web_hide": True,
            "canonical_factor": "factor17",
            "structure": "czsc_bi",
        },
    )


register_strategy(_bind(), replace=True)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy7Decision",
    "create_decision_engine",
    "analyze_bi_pl_ratio",
    "run_bi_pl_ratio",
    "run_strategy7",
    "run_strategy11",
    "BiPlRatioResult",
]
