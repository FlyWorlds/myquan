"""策略四 · 因子绑定：因子1·roll12 Top3 池 + 池内反转（因子3截面用法）。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.strategies.strategy4.portfolio import PORTFOLIO_DEFAULTS

STRATEGY_ID = "strategy4"
STRATEGY_NAME = "策略四"

_p = PORTFOLIO_DEFAULTS

FACTOR_BINDINGS = (
    bind_factor(
        "factor1",
        label="因子1·滚动12月评分建池",
        role="custom",
        score_mode=_p["score_mode"],
        pool_n=_p["pool_n"],
        filter_desc=(
            f"月末 {_p['score_mode']} 评分 Top{_p['pool_n']} → 次月可交易池（中证1000主板）"
        ),
    ),
    bind_factor(
        "factor3",
        label="池内反转选股",
        role="both",
        kind=_p["kind"],
        n=_p["n"],
        top_k=_p["top_k"],
        hold_days=_p["hold_days"],
        select_mode=_p["select_mode"],
        filter_desc=(
            f"仅池内 {_p['kind']}(n={_p['n']}) 日选 Top{_p['top_k']}，"
            f"持有{_p['hold_days']}日；收盘信号次日开盘"
        ),
    ),
)
