"""因子4 · 行情三态 regime（牛市 / 震荡 / 下跌）。

收盘确认，次日开盘生效；叠在因子1 上：
  · 买卖仍走因子1 开盘±pct
  · 阈值止损始终全清
  · 牛市 / 震荡：波段止盈（默认昨高触及 → 今开按档减仓/全清）
  · 下跌（含下跌震荡）：分档减仓止盈，余仓仍走阈值止损全清
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from strategy.momentum import (
    compute_momentum_raw,
    momentum_rules_text,
    raw_to_target,
)

DEFAULT_BULL_KIND = "roc_ma"
DEFAULT_BULL_PARAMS: dict[str, Any] = {
    "n": 60,
    "ma_n": 60,
    "enter": 0.0,
    "exit": 0.0,
    "buffer": 0.0,
}

# 三态行情（个股自身均线+动量）；与旧 bull_hold 并存
DEFAULT_REGIME_MA_N = 60
DEFAULT_REGIME_ROC_N = 20

# 因子4 默认止盈政策（相对买入价）
DEFAULT_FACTOR4_TP_TRIGGER = "prev_high"
DEFAULT_FACTOR4_TP_BULL: tuple[float, ...] = (0.20,)
DEFAULT_FACTOR4_TP_SIDEWAYS: tuple[float, ...] = (0.15,)
DEFAULT_FACTOR4_TP_BEAR: tuple[float, ...] = (0.08, 0.12, 0.18)
DEFAULT_FACTOR4_TP_REDUCE_BULL = 1.0  # 波段全清
DEFAULT_FACTOR4_TP_REDUCE_SIDEWAYS = 1.0
DEFAULT_FACTOR4_TP_REDUCE_BEAR = 1.0 / 3.0  # 下跌震荡分档减仓

REGIME_BULL = "bull"
REGIME_SIDEWAYS = "sideways"
REGIME_BEAR = "bear"


def raw_to_bull_target(
    raw: pd.Series,
    *,
    kind: str,
    params: dict[str, Any] | None = None,
) -> pd.Series:
    """旧版二值牛市状态；可用非对称阈值缩短低质量趋势保护期。"""
    p = {**DEFAULT_BULL_PARAMS, **(params or {})}
    if "enter_raw" not in p and "exit_raw" not in p:
        return raw_to_target(raw, kind=kind, params=p)

    enter = float(p.get("enter_raw", 0.0))
    exit_ = float(p.get("exit_raw", 0.0))
    if exit_ > enter:
        raise ValueError("factor4 exit_raw must be <= enter_raw")

    out = pd.Series(0.0, index=raw.index, dtype=float)
    state = 0.0
    for i, value in enumerate(raw.to_numpy()):
        if pd.isna(value):
            out.iloc[i] = state
            continue
        if state <= 0 and float(value) > enter:
            state = 1.0
        elif state >= 1 and float(value) < exit_:
            state = 0.0
        out.iloc[i] = state
    return out


def classify_market_regime(
    close: pd.Series,
    *,
    ma_n: int = DEFAULT_REGIME_MA_N,
    roc_n: int = DEFAULT_REGIME_ROC_N,
) -> pd.Series:
    """单票收盘价 → 牛/震/跌（当日确认，不含 shift）。

    bull: 收盘站上均线且 roc>0
    bear: 收盘跌破均线且 roc<0
    sideways: 其余（含上涨中的震荡、下跌中的反弹震荡）
    """
    px = close.astype(float)
    n = max(2, int(ma_n))
    r = max(1, int(roc_n))
    sma = px.rolling(n, min_periods=max(5, n // 3)).mean()
    roc = px / px.shift(r) - 1.0
    regime = pd.Series(REGIME_SIDEWAYS, index=px.index, dtype=object)
    bull = (px > sma) & (roc > 0)
    bear = (px < sma) & (roc < 0)
    return regime.mask(bull, REGIME_BULL).mask(bear, REGIME_BEAR)


def build_market_regime_series(
    daily: pd.DataFrame,
    *,
    ma_n: int = DEFAULT_REGIME_MA_N,
    roc_n: int = DEFAULT_REGIME_ROC_N,
) -> pd.DataFrame:
    """日线附加 regime_raw / regime_target / regime_exec（次日生效）。"""
    out = daily.copy()
    if "close" not in out.columns:
        raise KeyError("daily 缺少 close")
    raw = classify_market_regime(out["close"], ma_n=ma_n, roc_n=roc_n)
    out["regime_raw"] = raw
    out["regime_target"] = raw
    out["regime_exec"] = raw.shift(1)
    out["bull_raw"] = (raw == REGIME_BULL).astype(float)
    out["bull_target"] = out["bull_raw"]
    out["bull_exec"] = out["bull_raw"].shift(1)
    return out


def build_bull_regime(
    daily: pd.DataFrame,
    *,
    kind: str = DEFAULT_BULL_KIND,
    params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """兼容旧接口：在日线上附加 bull_raw / bull_target / bull_exec。"""
    p = {**DEFAULT_BULL_PARAMS, **(params or {})}
    kind = str(kind or DEFAULT_BULL_KIND).lower()
    out = daily.copy()
    raw = compute_momentum_raw(out, kind=kind, params=p)
    tgt = raw_to_bull_target(raw, kind=kind, params=p)
    out["bull_raw"] = raw
    out["bull_target"] = tgt
    out["bull_exec"] = tgt.shift(1)
    return out


def _date_key(value: Any) -> str:
    if hasattr(value, "strftime"):
        text = value.strftime("%Y-%m-%d")
    else:
        text = str(value)
    return text[:10] if len(text) >= 10 else text


def bull_regime_by_date(
    daily: pd.DataFrame,
    *,
    kind: str = DEFAULT_BULL_KIND,
    params: dict[str, Any] | None = None,
) -> dict[str, bool]:
    """date(YYYY-MM-DD) -> 当日开盘起是否处于牛市持股 regime。"""
    enriched = build_bull_regime(daily, kind=kind, params=params)
    out: dict[str, bool] = {}
    for _, row in enriched.iterrows():
        d = _date_key(row["date"])
        v = row.get("bull_exec")
        out[d] = bool(v == 1.0) if pd.notna(v) else False
    return out


def market_regime_by_date(
    daily: pd.DataFrame,
    *,
    ma_n: int = DEFAULT_REGIME_MA_N,
    roc_n: int = DEFAULT_REGIME_ROC_N,
) -> dict[str, str]:
    """date -> bull|sideways|bear（次日生效的 regime_exec）。"""
    enriched = build_market_regime_series(daily, ma_n=ma_n, roc_n=roc_n)
    out: dict[str, str] = {}
    for _, row in enriched.iterrows():
        d = _date_key(row["date"])
        v = row.get("regime_exec")
        if pd.isna(v) or v is None or str(v) == "nan":
            continue
        out[d] = str(v)
    return out


def resolve_factor4_tp_policy(
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """合并因子4 默认止盈政策。"""
    p = dict(params or {})
    return {
        "trigger": str(p.get("tp_trigger") or DEFAULT_FACTOR4_TP_TRIGGER),
        "bull_levels": tuple(p.get("tp_bull") or DEFAULT_FACTOR4_TP_BULL),
        "sideways_levels": tuple(p.get("tp_sideways") or DEFAULT_FACTOR4_TP_SIDEWAYS),
        "bear_levels": tuple(p.get("tp_bear") or DEFAULT_FACTOR4_TP_BEAR),
        "bull_reduce": float(
            p["tp_reduce_bull"]
            if p.get("tp_reduce_bull") is not None
            else DEFAULT_FACTOR4_TP_REDUCE_BULL
        ),
        "sideways_reduce": float(
            p["tp_reduce_sideways"]
            if p.get("tp_reduce_sideways") is not None
            else DEFAULT_FACTOR4_TP_REDUCE_SIDEWAYS
        ),
        "bear_reduce": float(
            p["tp_reduce_bear"]
            if p.get("tp_reduce_bear") is not None
            else DEFAULT_FACTOR4_TP_REDUCE_BEAR
        ),
        "ma_n": int(p.get("regime_ma_n") or DEFAULT_REGIME_MA_N),
        "roc_n": int(p.get("regime_roc_n") or DEFAULT_REGIME_ROC_N),
    }


def bull_rules_text(kind: str, params: dict[str, Any] | None = None) -> str:
    p = {**DEFAULT_BULL_PARAMS, **(params or {})}
    kind = str(kind or DEFAULT_BULL_KIND).lower()
    tp = resolve_factor4_tp_policy(p)
    base = momentum_rules_text(kind, p)
    bull_lv = "/".join(f"{x*100:.0f}" for x in tp["bull_levels"]) or "关"
    side_lv = "/".join(f"{x*100:.0f}" for x in tp["sideways_levels"]) or "关"
    bear_lv = "/".join(f"{x*100:.0f}" for x in tp["bear_levels"]) or "关"
    return (
        base.replace("因子3 — 动量因子", "因子4 — 行情三态 + 波段/分档止盈")
        + "\n【叠因子1】\n"
        "  · 买卖与阈值止损仍走因子1；触及开盘−pct 止损 → 全清\n"
        f"  · 行情三态（MA{tp['ma_n']}+ROC{tp['roc_n']}，收盘确认次日生效）\n"
        f"  · 牛市波段止盈：+{bull_lv}% × 减仓{tp['bull_reduce']*100:.0f}%\n"
        f"  · 震荡波段止盈：+{side_lv}% × 减仓{tp['sideways_reduce']*100:.0f}%\n"
        f"  · 下跌/下跌震荡分档减仓：+{bear_lv}% × 各减{tp['bear_reduce']*100:.0f}%\n"
        f"  · 止盈触发：{tp['trigger']}（prev_high=昨高触及今开卖）\n"
        "  · 可选兼容：旧版牛市暂停止损 / 放宽止损 / 开盘建仓\n"
    )


def factor4_rules_text(params: dict[str, Any] | None = None) -> str:
    return bull_rules_text(DEFAULT_BULL_KIND, params)


__all__ = [
    "DEFAULT_BULL_KIND",
    "DEFAULT_BULL_PARAMS",
    "DEFAULT_REGIME_MA_N",
    "DEFAULT_REGIME_ROC_N",
    "DEFAULT_FACTOR4_TP_TRIGGER",
    "DEFAULT_FACTOR4_TP_BULL",
    "DEFAULT_FACTOR4_TP_SIDEWAYS",
    "DEFAULT_FACTOR4_TP_BEAR",
    "DEFAULT_FACTOR4_TP_REDUCE_BULL",
    "DEFAULT_FACTOR4_TP_REDUCE_SIDEWAYS",
    "DEFAULT_FACTOR4_TP_REDUCE_BEAR",
    "REGIME_BULL",
    "REGIME_SIDEWAYS",
    "REGIME_BEAR",
    "build_bull_regime",
    "build_market_regime_series",
    "bull_regime_by_date",
    "market_regime_by_date",
    "classify_market_regime",
    "bull_rules_text",
    "factor4_rules_text",
    "raw_to_bull_target",
    "resolve_factor4_tp_policy",
]
