"""策略十二：因子18 恐慌空仓 + 因子21 涨停次日低开。"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy12.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy12.decision import (
    Strategy12Decision,
    create_decision_engine,
)
from strategy.strategies.strategy12.emotion_gate import emotion_flag_by_date


def _print_rules() -> str:
    head = compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)
    extra = """
----- 组合规则 -----
1. 因子21：昨日收盘涨停，今日低开 -4.5%～-0.3% 且未封涨停 → 开盘买入
2. 因子18：恐慌日（低开开盘跌停家数≥4）空仓
3. 退出：T+1 收盘清仓；一字跌停无法卖则顺延
4. 宇宙中证1000，每日最多 3 只，按低开越深优先
研究用途，非投资建议。
"""
    return head + "\n" + extra.strip()


def run_strategy12(
    cfg: Any = None,
    *,
    show_report: bool = False,
    verbose: bool = True,
    force_daily_refresh: bool = False,
) -> tuple[Any, Any]:
    del cfg, show_report, force_daily_refresh
    from strategy.strategies.strategy12.gap_reclaim import run_gap_reclaim_backtest

    out = run_gap_reclaim_backtest(verbose=verbose)
    return out.get("summary"), out.get("equity")


def _bind() -> StrategySpec:
    return StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "昨日收盘涨停、今日低开未封涨停则开盘买，T+1 收盘清；"
            "因子18 恐慌日空仓；中证1000 截面；研究组合，非默认盯盘"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy12,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s12", "lu_next_gap", "涨停次日低开", "策略十二"),
        implemented=True,
        meta={
            "default": False,
            "mode": "lu_next_gap",
            "research_only": True,
            "validation": "oos_failed",
            "factors": ("factor18", "factor21"),
            "backtest_cli": "backtest/strategy12_emotion_gate/run.py",
        },
    )


register_strategy(_bind(), replace=True)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy12Decision",
    "create_decision_engine",
    "run_strategy12",
    "emotion_flag_by_date",
]
