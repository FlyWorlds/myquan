"""策略六：绑定因子12，反转池近高 Top5 等权持有（研究候选）。"""

from strategy.core.protocols import bind_factor
from strategy.factor12_combo import DEFAULT_PARAMS

STRATEGY_ID = "strategy6"
STRATEGY_NAME = "策略六·反转池近高"

_p = DEFAULT_PARAMS
FACTOR_BINDINGS = (
    bind_factor(
        "factor12",
        role="both",
        label="因子12·反转池近高",
        **_p,
        filter_desc=(
            f"周频 {_p['mom_n']} 日涨幅最低 Top{_p['stage1_k']} 内，"
            f"贴近 {_p['high_n']} 日高点 Top{_p['stage2_k']}；"
            "本周收盘排名，下一周等权持有；研究候选，不替换策略五"
        ),
    ),
)
