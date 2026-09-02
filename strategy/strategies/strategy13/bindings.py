"""策略十三：策略1质量带 · 周频动量轮动（重叠留仓）。"""

from strategy.core.protocols import bind_factor
from strategy.s1_weekly_rotate import DEFAULT_PARAMS

STRATEGY_ID = "strategy13"
STRATEGY_NAME = "策略十三·S1质量带周频轮动"

_p = DEFAULT_PARAMS
FACTOR_BINDINGS = (
    bind_factor(
        "factor13a",
        label="质量带合格池",
        role="universe",
        filter_desc=(
            f"宽宇宙主板剔ST/≥{_p['max_price']:.0f}元；"
            f"上年质量带初选≤{_p['candidate_pool']}"
        ),
        enabled=True,
    ),
    bind_factor(
        "factor16",
        label="周动量排序（替位）",
        role="entry",
        mom_n=_p["mom_n"],
        top_k=_p["top_k"],
        filter_desc=(
            f"本周收盘近{_p['mom_n']}日涨幅 Top{_p['top_k']}；"
            "下一周等权，重叠票不强制换出"
        ),
        enabled=True,
    ),
)
