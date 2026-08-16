"""盯盘 · 因子4（牛市持股 regime）。

与 strategy.bull_regime / strategy7 per_symbol F4 同源。
日线收盘确认 → 次日生效；缓存按交易日刷新。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from strategy.bull_regime import bull_regime_by_date
from strategy.config import (
    FACTOR4_REPAIR_KAICHENG,
    FACTOR4_REPAIR_KCZZ,
    FACTOR4_REPAIR_TIANTONG,
    FACTOR4_REPAIR_UNIFIED,
)

# sina → (session_date, bull_map, kind, params_key)
_BULL_CACHE: dict[str, tuple[str, dict[str, bool], str, str]] = {}


def factor4_patch_for_code(code: str) -> dict[str, Any]:
    """按代码取策略七逐票 F4 推荐参数。"""
    c = "".join(ch for ch in str(code) if ch.isdigit()).zfill(6)[-6:]
    if c == "600552":
        return dict(FACTOR4_REPAIR_KAICHENG)
    if c == "600330":
        return dict(FACTOR4_REPAIR_TIANTONG)
    if c == "589680":
        return dict(FACTOR4_REPAIR_KCZZ)
    return dict(FACTOR4_REPAIR_UNIFIED)


def resolve_factor4_spec(item: dict[str, Any]) -> tuple[str, dict[str, Any], float]:
    """返回 (kind, params, stop_widen_mult)。优先用盯盘项覆盖。"""
    patch = factor4_patch_for_code(str(item.get("code") or ""))
    kind = str(item.get("factor4_kind") or patch.get("factor4_kind") or "roc_ma")
    params = dict(item.get("factor4_params") or patch.get("factor4_params") or {})
    widen = float(
        item.get("factor4_stop_widen_mult")
        if item.get("factor4_stop_widen_mult") is not None
        else (patch.get("factor4_stop_widen_mult") or 0.0)
    )
    return kind, params, widen


def _params_key(kind: str, params: dict[str, Any]) -> str:
    items = sorted((str(k), str(v)) for k, v in params.items())
    return f"{kind}|{items}"


def bull_exec_today(
    sina: str,
    session: str,
    daily: pd.DataFrame,
    *,
    kind: str,
    params: dict[str, Any],
) -> bool:
    """今日开盘起是否处于因子4 牛市持股（bull_exec）。"""
    sess = str(session)[:10]
    key = _params_key(kind, params)
    cached = _BULL_CACHE.get(sina)
    if cached and cached[0] == sess and cached[2] == kind and cached[3] == key:
        return bool(cached[1].get(sess, False))

    if daily is None or daily.empty:
        _BULL_CACHE[sina] = (sess, {}, kind, key)
        return False

    # 需要足够历史：roc_ma60 至少约 60+ 根
    bull_map = bull_regime_by_date(daily, kind=kind, params=params)
    _BULL_CACHE[sina] = (sess, bull_map, kind, key)
    return bool(bull_map.get(sess, False))


def effective_stop_pct(
    base_stop_pct: float,
    *,
    bull: bool,
    widen_mult: float,
) -> tuple[float, str]:
    """牛市下的有效止损比例与说明。

    Returns:
      (stop_pct, mode)  mode ∈ {normal, widened, suppressed}
    """
    base = float(base_stop_pct)
    if not bull:
        return base, "normal"
    w = float(widen_mult or 0.0)
    if w > 1.0:
        return base * w, "widened"
    # widen<=1：与回测 suppress 对齐 → 暂停止损
    return base, "suppressed"


def format_factor4_tag(*, bull: bool, mode: str, widen_mult: float) -> str:
    if not bull:
        return "非牛市·因子1止损"
    if mode == "widened":
        return f"牛市·止损放宽{float(widen_mult):.1f}x"
    if mode == "suppressed":
        return "牛市·暂停止损"
    return "牛市"
