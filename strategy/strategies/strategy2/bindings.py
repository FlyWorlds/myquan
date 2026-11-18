"""策略二 · 缠论图形形态全景扫描与盯盘策略因子绑定。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor

STRATEGY_ID = "strategy2"
STRATEGY_NAME = "策略二·缠论"


FACTOR_BINDINGS = (
    bind_factor(
        "factor8",
        label="缠论底背驰1买与类2买主升",
        role="both",
        base_freq="日线",
        confirm_freq="日线/30分钟",
        higher_freq="日线",
        candidate_timeout_bars=25,
        entry_rule="chan_divergence_buy1_then_buy2",
        strengthen_rule="volume_expansion_above_pivot",
        exit_rules=("break_pullback_stop", "target_take_profit", "sell2"),
        top_k=10,
        target_pct=0.15,
        filter_desc="出中枢下跌笔创出新低，MACD绿柱面积明显缩小形成动能底背驰(1买)；随后走出放量反弹浪，回踩不破1买低点(低点抬高)，底分型拐点确立类2买主升",
        enabled=True,
    ),
)


def strict_yin_filter(*args: object, **kwargs: object) -> bool:
    """旧 API 兼容：策略二已不再使用阴线过滤。"""
    del args, kwargs
    return True


__all__ = [
    "FACTOR_BINDINGS",
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "strict_yin_filter",
]
