"""策略六 · 因子绑定：因子3 选股 + 因子1 止损。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.open_break import DEFAULT_PCT
from strategy.strategies.strategy5.portfolio import PORTFOLIO_DEFAULTS

STRATEGY_ID = "strategy6"
STRATEGY_NAME = "因子3选股+因子1止损"

_p = PORTFOLIO_DEFAULTS

FACTOR_BINDINGS = (
    bind_factor(
        "factor3",
        role="entry",
        label="因子3·截面选股",
        kind=_p["kind"],
        n=_p["n"],
        top_k=_p["top_k"],
        hold_days=_p["hold_days"],
        min_score=_p["min_score"],
        ma_filter=_p["ma_filter"],
        mode=_p.get("mode"),
        n2=_p.get("n2"),
        w=_p.get("w"),
        filter_desc=(
            f"收盘截面选股：中证500+1000主板 mode={_p.get('mode')} "
            f"rev(n={_p['n']}"
            + (f"+{_p['n2']}" if _p.get("n2") else "")
            + f") Top{_p['top_k']} → 次日开盘买入；"
            f"最长持有{_p['hold_days']}日（未止损则开盘到期卖）"
        ),
    ),
    bind_factor(
        "factor1",
        role="exit",
        label="因子1·开盘止损",
        stop_pct=DEFAULT_PCT,
        filter_desc=(
            f"持仓后按当日开盘-{DEFAULT_PCT*100:.1f}%止损全清；"
            "T+1买入当日不卖；跌破按触发价（缺口低开按开盘价）"
        ),
    ),
)
