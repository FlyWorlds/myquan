"""策略三十七·跌停开板缠论反转策略 (Limit-Down Open-Board Chan Reversal Strategy)。

核心定位：
聚焦全 A 沪深主板正股（非 ST / 剔除创业板、科创板、北交所）。
捕捉在趋势离开下跌笔中出现的极端跌停撬板放量反转机会。
结合量价极端形态（日内触及 10% 跌停且收盘强力开板）与日线缠论形态（下跌笔进入 + 中枢震荡 + 离开下跌笔），
在趋势背驰段捕捉确定性反转买点。

实证与调参结论：
  · 调参锁定 90 天（3个月）最优中枢离开背驰窗口；
  · 样本外（2025-至今）验证完全有效，d1~d5 持有收益率全线为正，盈亏比 1.20；
  · 若在盘中触及跌停板挂单翘板买入，次日（d1）胜率高达 67.3%，平均收益 +3.03%，盈亏比 4.01。
"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy37.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy37.decision import Strategy37Decision, create_decision_engine


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def run_strategy37(cfg: Any = None, **kwargs: Any) -> Any:
    """运行策略三十七回测与信号统计。"""
    from scripts.run_limit_down_chan_research import run_research

    return run_research()


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "跌停开板缠论反转策略：全A主板跌停触及开板 + 缠论日线下跌笔+中枢+离开下跌笔；"
            "锁定3个月最优背驰窗口，捕捉极端情绪杀跌释放后的高盈亏比反弹机会，样本外d1~d5收益全为正。"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy37,
        default_config=None,
        strategy_cls=None,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s37", "跌停开板缠论", "limit_down_chan", "chan_reversal"),
        implemented=True,
        meta={
            "default": False,
            "mode": "reversal",
            "watch_tab": True,
            "factors": ("factor37",),
            "report_path": "reports/limit_down_chan/summary_metrics.json",
        },
    ),
    replace=True,
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy37Decision",
    "create_decision_engine",
    "run_strategy37",
]
