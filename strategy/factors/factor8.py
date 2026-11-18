"""因子8：CZSC 缠论结构与买卖点因子（底背驰1买与类2买主升）。"""

from strategy.chan.features import FACTOR_CANDIDATES
from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec


FACTOR_ID = "factor8"
FACTOR_NAME = "因子8-缠论结构"

RULES_TEXT = """
1. 经历显著前期下跌笔 a，随后震荡盘整构建缠论中枢；
2. 离开中枢走出下跌笔 b 创出新低，且 MACD 绿柱累加绝对值面积显著萎缩 (Sb < Sa * 0.88)，形成动能底背驰；
3. 底背驰点确立底分型形成 1 买，成交量明显放大展开反弹笔；
4. 1买放量反弹后回调，回调低点严格不破 1 买低点 (低点抬高)，在支撑位确立底分型拐点触发【类2买 / 预2买】；
5. 止损设于类2买回踩低点下方 (-1.5%~-2%)，目标以类2买展开主升波段为核心。
""".strip()


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description="CZSC缠论中枢底背驰1买识别、回调不破前低类2买主升确认与多级别走势结构特征",
    rules_text=RULES_TEXT,
    implemented=True,
    meta={
        "kind": "chan",
        "base_freq": "日线",
        "confirm_freq": "日线/30分钟",
        "entry": "chan_divergence_buy1_then_buy2",
        "exit": ("break_pullback_stop", "target_take_profit", "sell2"),
        "candidates": FACTOR_CANDIDATES,
        "czsc_version": "1.0.0rc8",
    },
)

register_factor(SPEC, replace=True)


__all__ = ["FACTOR_ID", "FACTOR_NAME", "RULES_TEXT", "SPEC"]
