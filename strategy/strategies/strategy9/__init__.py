"""策略九：低开跌停情绪 — 统计中证1000 低开开盘跌停家数，研判大盘当日涨跌。"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies.strategy9.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy9.limit_down_emotion import run_limit_down_emotion_backtest
from strategy.strategies.strategy9.sentiment_phase import _phase_ranges_text


def _print_rules() -> str:
    return f"""
================================================================================
  {STRATEGY_NAME}
================================================================================

【统计口径】
  · 宇宙：中证1000（剔 ST / 北交），2020→今
  · 低开开盘即跌停：开盘 < 昨收 且 开盘价在跌停价容差内
  · 大盘参照：上证指数 sh000001 收盘相对昨收涨跌幅

【情绪阶段】
  · {_phase_ranges_text()}

【方向研判（研究）】
  · 恐慌（家数偏多）→ 预判当日收跌
  · 平静（家数稀少）→ 预判当日收涨
  · 正常 → 样本内顺势偏空

仅供研究，不构成投资建议。
================================================================================
""".strip()


def run_strategy9_emotion(**kwargs: Any) -> dict[str, Any]:
    return run_limit_down_emotion_backtest(**kwargs)


def _bind() -> StrategySpec:
    return StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "统计中证1000 每日低开开盘跌停家数；"
            "按平静/正常/恐慌对照上证指数当日涨跌（2020→）"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy9_emotion,
        default_config=None,
        strategy_cls=None,
        print_rules=_print_rules,
        aliases=("s9e", "ld_emotion", "情绪策略", "低开跌停情绪", "策略九情绪"),
        implemented=True,
        meta={
            "default": False,
            "mode": "market_emotion",
            "backtest_cli": "backtest/strategy9_limit_down_emotion/run.py",
            "factors": (),
        },
    )


register_strategy(_bind())

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "run_strategy9_emotion",
    "run_limit_down_emotion_backtest",
]
