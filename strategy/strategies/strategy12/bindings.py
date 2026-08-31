"""策略十二 · 涨停次日低开：因子18 恐慌空仓 + 因子21 选股。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.factors.factor15 import GAP_MAX, GAP_MIN
from strategy.factors.factor18 import LD_OPEN_PANIC_MIN

STRATEGY_ID = "strategy12"
STRATEGY_NAME = "策略十二·涨停次日低开"

FACTOR_BINDINGS = (
    bind_factor(
        "factor18",
        label="低开跌停情绪择时",
        role="filter",
        filter_desc=f"中证1000 低开开盘跌停家数≥{LD_OPEN_PANIC_MIN}（恐慌）→ 当日空仓",
    ),
    bind_factor(
        "factor21",
        label="涨停次日低开",
        role="both",
        filter_desc=(
            f"昨收涨停且曾开板，今日 gap ∈ [{GAP_MIN:.1%}, {GAP_MAX:.1%}] 且未封涨停；"
            "上证昨收≤−2% 空仓；开盘买入，T+1 收盘清；低开越深优先，每日 Top3"
        ),
    ),
)

__all__ = ["STRATEGY_ID", "STRATEGY_NAME", "FACTOR_BINDINGS"]
