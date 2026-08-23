"""策略五：绑定因子11，近高 Top5 等权持有。"""

from strategy.core.protocols import bind_factor
from strategy.near_high_hold import DEFAULT_PARAMS

STRATEGY_ID = "strategy5"
STRATEGY_NAME = "策略五·近高Top5等权持有"

_p = DEFAULT_PARAMS
FACTOR_BINDINGS = (
    bind_factor(
        "factor11",
        role="both",
        label="因子11·两段近高选股",
        **_p,
        filter_desc=(
            f"周频 {_p['mom_n']} 日动量 Top{_p['stage1_k']} 内，"
            f"贴近 {_p['high_n']} 日高点 Top{_p['stage2_k']}；"
            "本周收盘排名，下一周等权持有"
        ),
    ),
)
