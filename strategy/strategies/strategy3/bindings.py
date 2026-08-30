"""策略三 · 首板晋级 + 因子1。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.open_break import DEFAULT_PCT

STRATEGY_ID = "strategy3"
STRATEGY_NAME = "策略三·首板晋级"

FACTOR_BINDINGS = (
    bind_factor(
        "factor1",
        label="开盘突破（晋级日执行）",
        role="both",
        entry_pct=DEFAULT_PCT,
        stop_pct=DEFAULT_PCT,
        prev_entry_mode="limit_up_ok",
        filter_desc=(
            "盯盘：宇宙=中证1000昨日收盘涨停全池；T-1情绪门槛决定今日可否做；"
            "晋级日因子1 ±阈值突破买，前日涨停不过阴/小阳过门；"
            "回测研究另含首板/gap/量比等过滤（见 backtest/strategy3_first_board）"
        ),
        enabled=True,
    ),
)
