"""策略二 · 缠论结构因子绑定。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor

STRATEGY_ID = "strategy2"
STRATEGY_NAME = "策略二·缠论"


FACTOR_BINDINGS = (
    bind_factor(
        "factor8",
        label="缠论小转大一买候选/二买确认",
        role="both",
        base_freq="日线",
        confirm_freq="30分钟",
        higher_freq="日线",
        candidate_timeout_bars=20,
        entry_rule="xiaozhuan_buy1_then_buy2",
        strengthen_rule="buy3",
        exit_rules=("sell2", "sell3"),
        top_k=10,
        target_pct=0.10,
        filter_desc="30分钟小转大一买入候选、二买确认；日线三买增强；日线二卖或三卖退出；截面排序用冻结因子组合",
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
