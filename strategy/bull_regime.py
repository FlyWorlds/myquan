"""因子4 · 行情三态 regime（牛市 / 震荡 / 下跌）。

收盘确认，次日开盘生效；叠在因子1 上：
  · 买卖仍走因子1 开盘±pct
  · 阈值止损始终全清
  · 行情默认：MA5/MA10 金叉→牛、死叉→跌、均线缠绕→震
  · 牛市：分档减仓止盈（默认 +20/30/40%，各减约 1/3）
  · 震荡：分档减仓止盈（默认 +10/15/20%，各减约 1/3）
  · 下跌：分档减仓止盈（默认 +5/10/15%，各减约 1/3）
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

# 三态行情：默认 MA5/MA10 金叉死叉+缠绕；可选旧 roc_ma
DEFAULT_REGIME_METHOD = "ma_cross"  # ma_cross | roc_ma
DEFAULT_REGIME_FAST = 5
DEFAULT_REGIME_SLOW = 10
# |MA快-MA慢|/收盘 < 该阈值 → 缠绕（震荡）
DEFAULT_REGIME_ENTANGLE_PCT = 0.008
# 近 N 日内金叉+死叉次数 ≥2 → 也视为缠绕
DEFAULT_REGIME_CROSS_LOOKBACK = 5
# 旧口径兼容
DEFAULT_REGIME_MA_N = 60
DEFAULT_REGIME_ROC_N = 20

# 因子4 默认止盈政策（相对买入价；默认昨高触及→今开卖）
DEFAULT_FACTOR4_TP_TRIGGER = "prev_high"
DEFAULT_FACTOR4_TP_BULL: tuple[float, ...] = (0.20, 0.30, 0.40)
DEFAULT_FACTOR4_TP_SIDEWAYS: tuple[float, ...] = (0.10, 0.15, 0.20)
DEFAULT_FACTOR4_TP_BEAR: tuple[float, ...] = (0.05, 0.10, 0.15)
DEFAULT_FACTOR4_TP_REDUCE_BULL = 1.0 / 3.0
DEFAULT_FACTOR4_TP_REDUCE_SIDEWAYS = 1.0 / 3.0
DEFAULT_FACTOR4_TP_REDUCE_BEAR = 1.0 / 3.0

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


def classify_market_regime_ma_cross(
    close: pd.Series,
    *,
    ma_fast: int = DEFAULT_REGIME_FAST,
    ma_slow: int = DEFAULT_REGIME_SLOW,
    entangle_pct: float = DEFAULT_REGIME_ENTANGLE_PCT,
    cross_lookback: int = DEFAULT_REGIME_CROSS_LOOKBACK,
) -> pd.Series:
    """MA快/慢：多头排列→牛，空头排列→跌，缠绕→震。

    缠绕：|MA快−MA慢|/收盘 < entangle_pct，或近 cross_lookback 日金叉+死叉≥2 次。
    """
    px = close.astype(float)
    f = max(2, int(ma_fast))
    s = max(f + 1, int(ma_slow))
    ma_f = px.rolling(f, min_periods=max(2, f // 2)).mean()
    ma_s = px.rolling(s, min_periods=max(3, s // 2)).mean()
    spread = (ma_f - ma_s).abs() / px.replace(0.0, pd.NA)
    golden = (ma_f > ma_s) & (ma_f.shift(1) <= ma_s.shift(1))
    death = (ma_f < ma_s) & (ma_f.shift(1) >= ma_s.shift(1))
    lb = max(2, int(cross_lookback))
    cross_n = (
        golden.astype(float) + death.astype(float)
    ).rolling(lb, min_periods=1).sum()
    entangled = (spread < float(entangle_pct)) | (cross_n >= 2.0)
    regime = pd.Series(REGIME_SIDEWAYS, index=px.index, dtype=object)
    bull = (~entangled) & (ma_f > ma_s)
    bear = (~entangled) & (ma_f < ma_s)
    return regime.mask(bull, REGIME_BULL).mask(bear, REGIME_BEAR)


def classify_market_regime_roc_ma(
    close: pd.Series,
    *,
    ma_n: int = DEFAULT_REGIME_MA_N,
    roc_n: int = DEFAULT_REGIME_ROC_N,
) -> pd.Series:
    """旧口径：站上均线且 roc>0→牛；跌破且 roc<0→跌；其余震。"""
    px = close.astype(float)
    n = max(2, int(ma_n))
    r = max(1, int(roc_n))
    sma = px.rolling(n, min_periods=max(5, n // 3)).mean()
    roc = px / px.shift(r) - 1.0
    regime = pd.Series(REGIME_SIDEWAYS, index=px.index, dtype=object)
    bull = (px > sma) & (roc > 0)
    bear = (px < sma) & (roc < 0)
    return regime.mask(bull, REGIME_BULL).mask(bear, REGIME_BEAR)


def classify_market_regime(
    close: pd.Series,
    *,
    method: str | None = None,
    ma_fast: int = DEFAULT_REGIME_FAST,
    ma_slow: int = DEFAULT_REGIME_SLOW,
    entangle_pct: float = DEFAULT_REGIME_ENTANGLE_PCT,
    cross_lookback: int = DEFAULT_REGIME_CROSS_LOOKBACK,
    ma_n: int = DEFAULT_REGIME_MA_N,
    roc_n: int = DEFAULT_REGIME_ROC_N,
) -> pd.Series:
    """单票收盘价 → 牛/震/跌（当日确认，不含 shift）。"""
    m = str(method or DEFAULT_REGIME_METHOD).lower()
    if m in ("roc_ma", "ma60_roc", "legacy"):
        return classify_market_regime_roc_ma(close, ma_n=ma_n, roc_n=roc_n)
    return classify_market_regime_ma_cross(
        close,
        ma_fast=ma_fast,
        ma_slow=ma_slow,
        entangle_pct=entangle_pct,
        cross_lookback=cross_lookback,
    )


def build_market_regime_series(
    daily: pd.DataFrame,
    *,
    method: str | None = None,
    ma_fast: int = DEFAULT_REGIME_FAST,
    ma_slow: int = DEFAULT_REGIME_SLOW,
    entangle_pct: float = DEFAULT_REGIME_ENTANGLE_PCT,
    cross_lookback: int = DEFAULT_REGIME_CROSS_LOOKBACK,
    ma_n: int = DEFAULT_REGIME_MA_N,
    roc_n: int = DEFAULT_REGIME_ROC_N,
) -> pd.DataFrame:
    """日线附加 regime_raw / regime_target / regime_exec（次日生效）。"""
    out = daily.copy()
    if "close" not in out.columns:
        raise KeyError("daily 缺少 close")
    raw = classify_market_regime(
        out["close"],
        method=method,
        ma_fast=ma_fast,
        ma_slow=ma_slow,
        entangle_pct=entangle_pct,
        cross_lookback=cross_lookback,
        ma_n=ma_n,
        roc_n=roc_n,
    )
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
    method: str | None = None,
    ma_fast: int = DEFAULT_REGIME_FAST,
    ma_slow: int = DEFAULT_REGIME_SLOW,
    entangle_pct: float = DEFAULT_REGIME_ENTANGLE_PCT,
    cross_lookback: int = DEFAULT_REGIME_CROSS_LOOKBACK,
    ma_n: int = DEFAULT_REGIME_MA_N,
    roc_n: int = DEFAULT_REGIME_ROC_N,
) -> dict[str, str]:
    """date -> bull|sideways|bear（次日生效的 regime_exec）。"""
    enriched = build_market_regime_series(
        daily,
        method=method,
        ma_fast=ma_fast,
        ma_slow=ma_slow,
        entangle_pct=entangle_pct,
        cross_lookback=cross_lookback,
        ma_n=ma_n,
        roc_n=roc_n,
    )
    out: dict[str, str] = {}
    for _, row in enriched.iterrows():
        d = _date_key(row["date"])
        v = row.get("regime_exec")
        if pd.isna(v) or v is None or str(v) == "nan":
            continue
        out[d] = str(v)
    return out


def _tp_levels(
    p: Mapping[str, Any],
    key: str,
    default: tuple[float, ...],
) -> tuple[float, ...]:
    """允许显式传空 tuple 关闭该行情止盈（`or` 会把 () 当成 falsy）。"""
    if key not in p or p[key] is None:
        return tuple(default)
    return tuple(p[key])


def resolve_factor4_tp_policy(
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """合并因子4 默认止盈与行情判定参数。"""
    p = dict(params or {})
    return {
        "trigger": str(p.get("tp_trigger") or DEFAULT_FACTOR4_TP_TRIGGER),
        "bull_levels": _tp_levels(p, "tp_bull", DEFAULT_FACTOR4_TP_BULL),
        "sideways_levels": _tp_levels(p, "tp_sideways", DEFAULT_FACTOR4_TP_SIDEWAYS),
        "bear_levels": _tp_levels(p, "tp_bear", DEFAULT_FACTOR4_TP_BEAR),
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
        "regime_method": str(
            p.get("regime_method") or DEFAULT_REGIME_METHOD
        ).lower(),
        "ma_fast": int(p.get("regime_ma_fast") or DEFAULT_REGIME_FAST),
        "ma_slow": int(p.get("regime_ma_slow") or DEFAULT_REGIME_SLOW),
        "entangle_pct": float(
            p["regime_entangle_pct"]
            if p.get("regime_entangle_pct") is not None
            else DEFAULT_REGIME_ENTANGLE_PCT
        ),
        "cross_lookback": int(
            p.get("regime_cross_lookback") or DEFAULT_REGIME_CROSS_LOOKBACK
        ),
        # 旧口径仍可读
        "ma_n": int(p.get("regime_ma_n") or DEFAULT_REGIME_MA_N),
        "roc_n": int(p.get("regime_roc_n") or DEFAULT_REGIME_ROC_N),
    }


def bull_rules_text(kind: str, params: dict[str, Any] | None = None) -> str:
    p = {**DEFAULT_BULL_PARAMS, **(params or {})}
    kind = str(kind or DEFAULT_BULL_KIND).lower()
    tp = resolve_factor4_tp_policy(p)
    base = momentum_rules_text(kind, p)
    bull_lv = "/".join(f"{x*100:.0f}" for x in tp["bull_levels"])
    side_lv = "/".join(f"{x*100:.0f}" for x in tp["sideways_levels"]) or "关"
    bear_lv = "/".join(f"{x*100:.0f}" for x in tp["bear_levels"]) or "关"
    if bull_lv:
        bull_line = (
            f"  · 牛市分档减仓：+{bull_lv}% × 各减{tp['bull_reduce']*100:.0f}%\n"
        )
    else:
        bull_line = "  · 牛市：仅按开盘阈值执行，不设止盈\n"
    method = str(tp["regime_method"])
    if method in ("roc_ma", "ma60_roc", "legacy"):
        regime_line = (
            f"  · 行情三态（旧：MA{tp['ma_n']}+ROC{tp['roc_n']}，收盘确认次日生效）\n"
        )
    else:
        regime_line = (
            f"  · 行情三态（MA{tp['ma_fast']}/MA{tp['ma_slow']}："
            f"金叉多头→牛、死叉空头→跌、"
            f"|差|/价<{tp['entangle_pct']*100:.1f}%或近{tp['cross_lookback']}日交叉≥2→缠绕震；"
            f"收盘确认次日生效）\n"
        )
    return (
        base.replace("因子3 — 动量因子", "因子4 — 行情三态 + 分档止盈")
        + "\n【叠因子1】\n"
        + "  · 买卖与阈值止损仍走因子1；触及开盘−pct 止损 → 全清\n"
        + regime_line
        + bull_line
        + f"  · 震荡分档减仓：+{side_lv}% × 各减{tp['sideways_reduce']*100:.0f}%\n"
        + f"  · 下跌分档减仓：+{bear_lv}% × 各减{tp['bear_reduce']*100:.0f}%\n"
        + f"  · 止盈触发：{tp['trigger']}（prev_high=昨高触及今开卖；无档时不适用）\n"
        + "  · 可选兼容：旧版牛市暂停止损 / 放宽止损 / 开盘建仓\n"
    )


def factor4_rules_text(params: dict[str, Any] | None = None) -> str:
    return bull_rules_text(DEFAULT_BULL_KIND, params)


__all__ = [
    "DEFAULT_BULL_KIND",
    "DEFAULT_BULL_PARAMS",
    "DEFAULT_REGIME_METHOD",
    "DEFAULT_REGIME_FAST",
    "DEFAULT_REGIME_SLOW",
    "DEFAULT_REGIME_ENTANGLE_PCT",
    "DEFAULT_REGIME_CROSS_LOOKBACK",
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
    "classify_market_regime_ma_cross",
    "classify_market_regime_roc_ma",
    "bull_rules_text",
    "factor4_rules_text",
    "raw_to_bull_target",
    "resolve_factor4_tp_policy",
]
