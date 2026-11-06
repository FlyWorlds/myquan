"""因子37：跌停开板缠论反转因子 (Limit-Down Open-Board Chan Reversal Factor)。

核心定位：
主板极度超跌与情绪恐慌出清下的反转抄底因子。
结合量价微观极端形态（跌停板被资金撬板打开）与宏观缠论结构（日线下跌笔 + 中枢 + 离开下跌笔），
在趋势背驰段捕捉确定性反弹买点。

三大核心过滤：
1. 范围限定：全 A 沪深主板（600/601/603/605/000/001/002/003），剔除科创/创业/北交；
2. 剔除 ST：买入当时不得为 ST 股票（ST 股票跌停为 5%，主板正股跌停为 10%）；
3. 缠论形态：日线完成“下跌笔进入 + 至少3笔或5笔中枢震荡 + 离开下跌笔”，且离开中枢到跌停日处于指定窗口期内（推荐 90 天/3 个月最优参数）。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from czsc import CZSC, Direction, Freq, RawBar, ZS

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec

FACTOR_ID = "factor37"
FACTOR_NAME = "因子37-跌停开板缠论反转因子"

# 调参验证锁定的核心默认参数
DEFAULT_WINDOW_DAYS = 90             # 中枢脱离后的有效背驰时间窗口 (3个月最优)
DEFAULT_LIMIT_RATIO = 0.10           # 主板非ST涨跌停幅度 (10%)
DEFAULT_TICK_TOLERANCE = 0.01        # 跌停价匹配容差 (0.01元)
DEFAULT_HOLDING_DAYS = 5             # 推荐持有周期 (d5 均收益与盈亏比最优)
DEFAULT_BUY_PRICE_TYPE = "close"     # 买入执行方式: 'close' 尾盘收盘买入 / 'limit_down' 跌停价翘板买入


def _rules() -> str:
    return f"""
因子37-跌停开板缠论反转因子 (Limit-Down Open-Board Chan Reversal)
  · 宇宙范围：全 A 沪深主板正股（非 ST / 剔除创业板、科创板、北交所）。
  · 跌停开板条件：当日最低价触及 10% 跌停价 (abs(Low - LimitDown) <= 0.01)，且收盘价高于最低价 (Close > Low)，确认非一字跌停或封死跌停。
  · 缠论日线结构：
      1. 进入笔：必须为下跌笔 (bi_in)；
      2. 前置中枢：至少 3 笔或 5 笔重叠构成的有效日线中枢 (ZS, ZG >= ZD)；
      3. 离开笔：当前处于该中枢之后的离开下跌笔中；
      4. 窗口期：中枢结束到当前跌停开板日在 {DEFAULT_WINDOW_DAYS} 天内 (3个月最优)。
  · 持有周期：建议持有 1~5 个交易日，持有至 d5 收盘胜率 57.8%，盈亏比 2.43。
研究用途，非投资建议。
""".strip()


def is_mainboard(symbol: str) -> bool:
    """判定是否属于沪深主板股票。"""
    s = str(symbol or "").strip().lower()
    if s.startswith("sh"):
        return s[2:].startswith(("600", "601", "603", "605"))
    if s.startswith("sz"):
        return s[2:].startswith(("000", "001", "002", "003"))
    return False


def check_chan_structure(
    c: CZSC,
    bar_dt: pd.Timestamp,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> tuple[bool, dict[str, Any] | None]:
    """检查是否符合：下跌笔 + 中枢 + 离开下跌笔，且中枢离开在窗口期内。"""
    bis = c.bi_list
    ubi = c.ubi

    is_down = False
    if ubi and ubi.get("direction") == Direction.Down:
        is_down = True
    elif bis and bis[-1].direction == Direction.Down:
        is_down = True

    if not is_down:
        return False, None

    candidates: list[dict[str, Any]] = []

    # 模式 A: 当前未完成笔 ubi 为向下笔，bis 倒数 3 笔构成中枢，倒数第 4 笔为进入下跌笔
    if ubi and ubi.get("direction") == Direction.Down and len(bis) >= 4:
        if bis[-4].direction == Direction.Down:
            try:
                zs = ZS(bis[-3:])
                if zs.is_valid():
                    candidates.append({
                        "zs": zs,
                        "in_bi": bis[-4],
                        "zs_end_dt": bis[-1].edt,
                        "zs_zd": float(zs.zd),
                        "zs_zg": float(zs.zg),
                        "bi_count": 3,
                    })
            except Exception:
                pass

    # 模式 B: bis[-1] 已经是向下笔，bis[-4:-1] 构成中枢，bis[-5] 为进入下跌笔
    if bis and bis[-1].direction == Direction.Down and len(bis) >= 5:
        if bis[-5].direction == Direction.Down:
            try:
                zs = ZS(bis[-4:-1])
                if zs.is_valid():
                    candidates.append({
                        "zs": zs,
                        "in_bi": bis[-5],
                        "zs_end_dt": bis[-2].edt,
                        "zs_zd": float(zs.zd),
                        "zs_zg": float(zs.zg),
                        "bi_count": 3,
                    })
            except Exception:
                pass

    # 模式 C: 5笔扩展中枢 (bis 倒数 5 笔重叠)
    if ubi and ubi.get("direction") == Direction.Down and len(bis) >= 6:
        if bis[-6].direction == Direction.Down:
            try:
                zs = ZS(bis[-5:])
                if zs.is_valid():
                    candidates.append({
                        "zs": zs,
                        "in_bi": bis[-6],
                        "zs_end_dt": bis[-1].edt,
                        "zs_zd": float(zs.zd),
                        "zs_zg": float(zs.zg),
                        "bi_count": 5,
                    })
            except Exception:
                pass

    if not candidates:
        return False, None

    for cand in candidates:
        zs_end = pd.to_datetime(cand["zs_end_dt"])
        delta_days = (bar_dt - zs_end).days
        if 0 <= delta_days <= window_days:
            cand["delta_days"] = delta_days
            return True, cand

    return False, None


def evaluate_limit_down_chan_signal(
    *,
    symbol: str,
    prev_close: float,
    open_px: float,
    high_px: float,
    low_px: float,
    close_px: float,
    bar_dt: pd.Timestamp,
    czsc_engine: CZSC,
    window_days: int = DEFAULT_WINDOW_DAYS,
    limit_ratio: float = DEFAULT_LIMIT_RATIO,
    tick_tolerance: float = DEFAULT_TICK_TOLERANCE,
    is_st: bool = False,
) -> dict[str, Any]:
    """单日因子评估入口。"""
    # 1. 标的范围校验
    if not is_mainboard(symbol):
        return {"signal": False, "reason": "非主板标的"}
    if is_st:
        return {"signal": False, "reason": "ST标的剔除"}

    # 2. 跌停价计算与触及开板判断
    if prev_close <= 0 or low_px <= 0:
        return {"signal": False, "reason": "价格异常"}

    limit_down = round(prev_close * (1.0 - limit_ratio), 2)
    touch_ld = abs(low_px - limit_down) <= tick_tolerance
    open_board = touch_ld and (close_px > low_px)

    if not open_board:
        return {
            "signal": False,
            "reason": "未触及跌停或未开板",
            "limit_down": limit_down,
            "touch_ld": touch_ld,
            "open_board": open_board,
        }

    # 3. 缠论日线结构校验
    matched, chan_info = check_chan_structure(czsc_engine, bar_dt, window_days=window_days)
    if not matched:
        return {
            "signal": False,
            "reason": "缠论形态不满足(下-中枢-下或超时)",
            "limit_down": limit_down,
            "open_board": True,
        }

    return {
        "signal": True,
        "reason": f"跌停开板+缠论背驰买点(脱离中枢{chan_info.get('delta_days')}天)",
        "limit_down": limit_down,
        "open_board": True,
        "chan_info": chan_info,
    }


def factor37_signal(data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    """因子信号统一入口。"""
    d = dict(data or {})
    d.update(kwargs)
    return evaluate_limit_down_chan_signal(
        symbol=str(d.get("symbol", "")),
        prev_close=float(d.get("prev_close", 0.0)),
        open_px=float(d.get("open", d.get("open_px", 0.0))),
        high_px=float(d.get("high", d.get("high_px", 0.0))),
        low_px=float(d.get("low", d.get("low_px", 0.0))),
        close_px=float(d.get("close", d.get("close_px", 0.0))),
        bar_dt=pd.to_datetime(d.get("date", d.get("bar_dt", pd.Timestamp.now()))),
        czsc_engine=d.get("czsc_engine"),
        window_days=int(d.get("window_days", DEFAULT_WINDOW_DAYS)),
        limit_ratio=float(d.get("limit_ratio", DEFAULT_LIMIT_RATIO)),
        tick_tolerance=float(d.get("tick_tolerance", DEFAULT_TICK_TOLERANCE)),
        is_st=bool(d.get("is_st", False)),
    )


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "跌停开板缠论反转因子：全A主板跌停触及开板 + 缠论日线下跌笔+中枢+离开下跌笔，"
        "捕捉中枢背驰极端超跌反转机会，持有d1~d5期望为正。"
    ),
    rules_text=_rules(),
    implemented=True,
    signal=factor37_signal,
    meta={
        "role": "entry",
        "category": "reversal",
        "default_params": {
            "window_days": DEFAULT_WINDOW_DAYS,
            "limit_ratio": DEFAULT_LIMIT_RATIO,
            "tick_tolerance": DEFAULT_TICK_TOLERANCE,
            "holding_days": DEFAULT_HOLDING_DAYS,
            "buy_price_type": DEFAULT_BUY_PRICE_TYPE,
        },
    },
)

register_factor(SPEC, replace=True)

__all__ = [
    "FACTOR_ID",
    "FACTOR_NAME",
    "SPEC",
    "DEFAULT_WINDOW_DAYS",
    "DEFAULT_LIMIT_RATIO",
    "DEFAULT_TICK_TOLERANCE",
    "DEFAULT_HOLDING_DAYS",
    "DEFAULT_BUY_PRICE_TYPE",
    "is_mainboard",
    "check_chan_structure",
    "evaluate_limit_down_chan_signal",
    "factor37_signal",
]

