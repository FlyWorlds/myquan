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
            "盯盘：宇宙=中证1000昨日收盘涨停全池；"
            "T-1 连板梯度（lb≥2、h2～5）决定今日可否做；"
            "T-1 涨停家数展示冰点≤6/正常7～14/高潮≥15（与门槛独立）；"
            "晋级日因子1 ±阈值突破买；回测另含首板/gap/量比（见 strategy3_first_board）"
        ),
        enabled=True,
    ),
)
