"""因子28：紫阳真君 — 国泰海通/国泰君安武汉紫阳东路近 3 个月龙虎榜成交池。"""

from __future__ import annotations

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.ziyang_universe import (
    DEFAULT_PICKS_PATH,
    SEAT_ALIASES,
    SEAT_NAME,
    load_picks,
    pick_codes,
    refresh_pool,
)

FACTOR_ID = "factor28"
FACTOR_NAME = "因子28-紫阳真君"


def _rules() -> str:
    return f"""
因子28·紫阳真君（滚动近 3 个月席位成交池）
  · 席位：{SEAT_NAME}（历史亦称国泰君安武汉紫阳东路；别名见绑定）
  · 口径：东财营业部龙虎榜交易明细中近 90 日出现过买/卖的股票并集
  · 排序：上榜日数 ↓、买入额 ↓、净买额 ↓
  · 标签：b7 席位库民间映射「消闲派」（非官方认定）
  · CLI：`python strategy/run_ziyang_pool.py`
  · 用途：策略十七宇宙；买卖复用因子26/2（因子22 默认关）
研究用途，非投资建议。席位身份为规则/观测映射，不等于官方认定。
""".strip()


def signal(**kwargs):  # noqa: ANN003
    payload = load_picks()
    return {
        "label": payload.get("label"),
        "window_start": payload.get("window_start"),
        "window_end": payload.get("window_end"),
        "n_picks": int(payload.get("n_picks") or 0),
        "codes": pick_codes(payload),
        "as_of": payload.get("as_of"),
        "seat_name": payload.get("seat_name") or SEAT_NAME,
        **kwargs,
    }


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "国泰海通/国泰君安武汉紫阳东路近3个月龙虎榜成交并集；"
        "按上榜日数/买入额排序；策略十七宇宙"
    ),
    rules_text=_rules(),
    implemented=True,
    signal=signal,
    meta={
        "kind": "lhb_seat_universe",
        "category": "sentiment",
        "horizon": "rolling_3m",
        "seat_name": SEAT_NAME,
        "seat_aliases": list(SEAT_ALIASES),
        "picks_path": str(DEFAULT_PICKS_PATH.as_posix()),
        "strategy": "strategy17",
        "docs": "docs/FACTOR28.md",
        "refresh": refresh_pool,
    },
)

register_factor(SPEC)
