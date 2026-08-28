"""策略十二 · 因子14 竞价一字联动选股。"""

from strategy.auction_yizi_linkage import DEFAULT_PARAMS
from strategy.core.protocols import bind_factor

STRATEGY_ID = "strategy12"
STRATEGY_NAME = "策略十二·竞价一字联动选股"

_p = DEFAULT_PARAMS
FACTOR_BINDINGS = (
    bind_factor(
        "factor14",
        role="both",
        label="因子14·竞价一字联动",
        **_p,
        filter_desc=(
            f"当日竞价/开盘一字为题材锚；同代表题材内开盘高开 "
            f"{_p['min_open_gap']:.1%}–{_p['max_open_gap']:.1%}、非一字涨停；"
            f"按高开×题材内一字龙头数排序 Top{_p['top_k']}；"
            f"T 开盘等权持有 {_p['hold_days']} 日"
        ),
    ),
)
