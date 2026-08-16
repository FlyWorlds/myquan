"""策略八：绑定因子7行业 ETF 双动量。"""

from strategy.core.protocols import bind_factor
from strategy.industry_residual_momentum import DEFAULT_PARAMS

STRATEGY_ID = "strategy8"
STRATEGY_NAME = "行业ETF双动量"

_p = DEFAULT_PARAMS
FACTOR_BINDINGS = (
    bind_factor(
        "factor7",
        role="both",
        label="因子7·行业ETF双动量",
        **_p,
        filter_desc=(
            f"月末以{_p['momentum_months']}月普通动量和"
            f"{_p['pca_window_months']}月PCA改进残差动量各50%合成，"
            f"选择Top{_p['top_k']}，下一交易日开盘等权调仓"
        ),
    ),
)

