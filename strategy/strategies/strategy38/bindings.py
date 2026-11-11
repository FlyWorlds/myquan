"""策略三十八·地量起爆多维选股 · 因子绑定。

四步量化选股逻辑与因子绑定：
Step 1: 绝对风控（一票否决） -> 因子35-多维复合空仓因子
Step 2: 底池清洗（基本面过滤） -> 因子13A-质量带契合选股
Step 3: 核心进攻（日线形态筛选） -> 因子34-地量转放量动量
Step 4: 买点生成（执行层） -> 因子8-缠论结构 + 因子33-回落后攻击波
"""

from __future__ import annotations

from strategy.core.protocols import bind_factor

STRATEGY_ID = "strategy38"
STRATEGY_NAME = "策略三十八·地量起爆多维选股"

FACTOR_BINDINGS = (
    # Step 1: 绝对风控（一票否决）
    bind_factor(
        "factor35",
        label="大盘多维空仓避险",
        role="risk",
        filter_desc="大盘跌破MA60生命线或全市场广度进入极端踩踏时，一票否决强制空仓",
        enabled=True,
    ),
    # Step 2: 底池清洗（基本面/质地过滤）
    bind_factor(
        "factor13a",
        label="质量带契合选股",
        role="universe",
        filter_desc="全市场股票基本面与质地清洗，剔除ST/高回撤/低流动性标的",
        enabled=True,
    ),
    # Step 3: 核心进攻（日线形态筛选）
    bind_factor(
        "factor34",
        label="地量转放量动量起爆",
        role="entry",
        lookback=60,
        max_age=10,
        volume_multiple=2.0,
        body_min=0.05,
        filter_desc="前期60日地量沉淀 + 近期1~10日放量2倍以上且大阳线(>=5%)起爆",
        enabled=True,
    ),
    # Step 4: 买点生成（执行层：缠论买点确认与挂单价位）
    bind_factor(
        "factor8",
        label="缠论结构买点",
        role="both",
        filter_desc="日线底分型确立与向上一笔初生确认，辅助确认背驰与起爆有效性",
        enabled=True,
    ),
    bind_factor(
        "factor33",
        label="回落后攻击波挂单",
        role="entry",
        threshold_pct=0.025,
        tick=0.01,
        filter_desc="次日挂单买入价格计算与回落起爆买点确认逻辑",
        enabled=True,
    ),
)

__all__ = ["STRATEGY_ID", "STRATEGY_NAME", "FACTOR_BINDINGS"]
