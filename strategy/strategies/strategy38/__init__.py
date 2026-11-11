"""策略三十八·地量起爆多维选股 (Low-Volume Breakout Multi-Factor Strategy)。

核心架构与逻辑闭环：
Step 1: 绝对风控（一票否决） -> 因子35-多维复合空仓因子；大盘弱势时一票否决空仓防守。
Step 2: 底池清洗（基本面过滤） -> 因子13A-质量带契合选股；剔除ST与非主板，筛选质地达标底池。
Step 3: 核心进攻（日线形态筛选） -> 因子34-地量转放量动量；寻找“前期长周期缩量+近期底部倍量起爆”标的。
Step 4: 买点生成（执行层） -> 结合因子8缠论结构与因子33攻击波，输出次日挂单买入价格和买点确认逻辑。
"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy38.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy38.decision import (
    Strategy38Decision,
    create_decision_engine,
)
from strategy.strategies.strategy38.pipeline import run_strategy38_pipeline


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def run_strategy38(cfg: Any = None, **kwargs: Any) -> dict[str, Any]:
    """运行策略三十八选股与买点生成管道。"""
    return run_strategy38_pipeline(**kwargs)


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "地量起爆多维选股策略：Step 1 因子35大盘一票否决空仓；"
            "Step 2 因子13A主板基本面质地清洗；"
            "Step 3 因子34长周期缩量+底部倍量长阳起爆筛选；"
            "Step 4 因子8/33缠论结构确认与次日挂单买点生成。"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy38,
        default_config=None,
        strategy_cls=None,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s38", "地量起爆", "缩量起爆", "vol_breakout", "low_vol_breakout"),
        implemented=True,
        meta={
            "default": False,
            "mode": "momentum_breakout",
            "watch_tab": True,
            "factors": ("factor35", "factor13a", "factor34", "factor8", "factor33"),
        },
    ),
    replace=True,
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy38Decision",
    "create_decision_engine",
    "run_strategy38",
    "run_strategy38_pipeline",
]
