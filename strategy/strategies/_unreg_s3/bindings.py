"""策略三 · 因子绑定：动量因子组合 · 因子3。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.strategies._unreg_s5.portfolio import PORTFOLIO_DEFAULTS

STRATEGY_ID = "strategy3"
STRATEGY_NAME = "策略三"

_p = PORTFOLIO_DEFAULTS

FACTOR_BINDINGS = (
    bind_factor(
        "factor3",
        role="both",
        label="因子3·动量组合",
        kind=_p["kind"],
        n=_p["n"],
        top_k=_p["top_k"],
        hold_days=_p["hold_days"],
        min_score=_p["min_score"],
        ma_filter=_p["ma_filter"],
        filter_desc=(
            f"截面组合：中证500+1000主板 mode={_p.get('mode')} "
            f"rev(n={_p['n']}"
            + (f"+{_p['n2']}" if _p.get("n2") else "")
            + f") 日选Top{_p['top_k']}，持有{_p['hold_days']}日；收盘信号次日开盘"
        ),
    ),
)
