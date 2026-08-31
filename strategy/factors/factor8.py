"""因子8：CZSC 缠论结构与买卖点因子。"""

from strategy.chan.features import FACTOR_CANDIDATES
from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec


FACTOR_ID = "factor8"
FACTOR_NAME = "因子8-缠论结构"

RULES_TEXT = """
一买仅进入候选；候选期内出现二买才确认首次开仓。
三买增强截面排序或延续持仓，不绕过二买确认。
持仓后二卖或三卖退出；A股买入当日不可卖。
信号在日线收盘形成，下一交易日开盘成交。
30分钟只用于判断小转大买点：日线向下笔/一买/底背驰当日出现30分钟一买或二买。
连续结构特征逐时点做MAD去极值和截面z-score。
""".strip()


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description="CZSC一/二/三类买卖点、笔、中枢、背驰和多级别环境特征",
    rules_text=RULES_TEXT,
    implemented=True,
    meta={
        "kind": "chan",
        "base_freq": "日线",
        "confirm_freq": "30分钟",
        "entry": "xiaozhuan_buy1_then_buy2",
        "exit": ("sell2", "sell3"),
        "candidates": FACTOR_CANDIDATES,
        "czsc_version": "1.0.0rc8",
    },
)

register_factor(SPEC, replace=True)


__all__ = ["FACTOR_ID", "FACTOR_NAME", "RULES_TEXT", "SPEC"]
