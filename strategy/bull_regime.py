"""因子4 · 行情三态 regime（牛市 / 震荡 / 下跌）。

收盘确认，次日开盘生效；叠在因子1 上：
  · 买卖仍走因子1 开盘±pct
  · 阈值止损始终全清
  · 行情默认：MA5/MA10 尾盘金叉/死叉粘性状态（有效交叉后持有期跟档，直到反向交叉）
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

# 三态行情：默认 MA5/MA10 金叉死叉粘性；可选 macd_cross / roc_ma
DEFAULT_REGIME_METHOD = "ma_cross"  # ma_cross | macd_cross | roc_ma
DEFAULT_REGIME_FAST = 5
DEFAULT_REGIME_SLOW = 10
DEFAULT_MACD_FAST = 12
DEFAULT_MACD_SLOW = 26
DEFAULT_MACD_SIGNAL = 9
# |MA快-MA慢|/收盘 < 该阈值 → 缠绕（震荡）；粘性交叉模式基本不用
DEFAULT_REGIME_ENTANGLE_PCT = 0.008
# 近 N 日内金叉+死叉次数 ≥2 → 也视为缠绕
DEFAULT_REGIME_CROSS_LOOKBACK = 5
# 力度诊断用；粘性切换默认不拦交叉（strength_min=0）
DEFAULT_REGIME_STRENGTH_MIN = 0.0
DEFAULT_REGIME_SLOPE_N = 3
DEFAULT_REGIME_SLOPE_WEIGHT = 0.5
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


def ma_cross_strength(
    close: pd.Series,
    *,
    ma_fast: int = DEFAULT_REGIME_FAST,
    ma_slow: int = DEFAULT_REGIME_SLOW,
    slope_n: int = DEFAULT_REGIME_SLOPE_N,
    slope_weight: float = DEFAULT_REGIME_SLOPE_WEIGHT,
) -> pd.DataFrame:
    """计算 MA 快慢线价差力度与方向性斜率力度。

    strength = |MA快−MA慢|/收盘 + slope_weight × max(0, 顺势斜率)
    顺势斜率：多头用 MA快 近 slope_n 日涨幅；空头用跌幅绝对值。
    """
    px = close.astype(float)
    f = max(2, int(ma_fast))
    s = max(f + 1, int(ma_slow))
    n = max(1, int(slope_n))
    ma_f = px.rolling(f, min_periods=max(2, f // 2)).mean()
    ma_s = px.rolling(s, min_periods=max(3, s // 2)).mean()
    spread = (ma_f - ma_s).abs() / px.replace(0.0, pd.NA)
    slope = ma_f / ma_f.shift(n) - 1.0
    long_side = ma_f > ma_s
    # 多头只计上斜，空头只计下斜
    dir_slope = slope.where(long_side, -slope).clip(lower=0.0)
    strength = spread.fillna(0.0) + float(slope_weight) * dir_slope.fillna(0.0)
    golden = (ma_f > ma_s) & (ma_f.shift(1) <= ma_s.shift(1))
    death = (ma_f < ma_s) & (ma_f.shift(1) >= ma_s.shift(1))
    return pd.DataFrame(
        {
            "ma_fast": ma_f,
            "ma_slow": ma_s,
            "spread": spread,
            "slope": slope,
            "dir_slope": dir_slope,
            "strength": strength,
            "golden": golden.fillna(False),
            "death": death.fillna(False),
        },
        index=px.index,
    )


def _sticky_from_crosses(
    golden: pd.Series,
    death: pd.Series,
    *,
    strength: pd.Series | None = None,
    strength_min: float = 0.0,
) -> pd.Series:
    """金叉/死叉事件 → 粘性牛/跌状态。"""
    g = golden.fillna(False)
    d = death.fillna(False)
    thr = float(strength_min)
    if thr > 0 and strength is not None:
        s = strength.fillna(0.0)
        valid_gc = g & (s >= thr)
        valid_dc = d & (s >= thr)
    else:
        valid_gc = g
        valid_dc = d
    out = []
    state = REGIME_SIDEWAYS
    for i in range(len(g)):
        if bool(valid_gc.iloc[i]):
            state = REGIME_BULL
        elif bool(valid_dc.iloc[i]):
            state = REGIME_BEAR
        out.append(state)
    return pd.Series(out, index=g.index, dtype=object)


def classify_market_regime_ma_cross(
    close: pd.Series,
    *,
    ma_fast: int = DEFAULT_REGIME_FAST,
    ma_slow: int = DEFAULT_REGIME_SLOW,
    entangle_pct: float = DEFAULT_REGIME_ENTANGLE_PCT,
    cross_lookback: int = DEFAULT_REGIME_CROSS_LOOKBACK,
    strength_min: float = 0.0,
    slope_n: int = DEFAULT_REGIME_SLOPE_N,
    slope_weight: float = DEFAULT_REGIME_SLOPE_WEIGHT,
) -> pd.Series:
    """MA快/慢金叉死叉「粘性状态机」→ 牛/震/跌。

    每日尾盘结算交叉：
      · 金叉 → 切入牛市；持有期止盈按牛市档，直到死叉
      · 死叉 → 切入下跌；持有期止盈按下跌档，直到金叉
      · 尚未出现过交叉 → 震荡
    """
    del entangle_pct, cross_lookback
    feat = ma_cross_strength(
        close.astype(float),
        ma_fast=ma_fast,
        ma_slow=ma_slow,
        slope_n=slope_n,
        slope_weight=slope_weight,
    )
    return _sticky_from_crosses(
        feat["golden"],
        feat["death"],
        strength=feat["strength"],
        strength_min=strength_min,
    )


def macd_cross_features(
    close: pd.Series,
    *,
    fast: int = DEFAULT_MACD_FAST,
    slow: int = DEFAULT_MACD_SLOW,
    signal: int = DEFAULT_MACD_SIGNAL,
) -> pd.DataFrame:
    """标准 MACD：DIF=EMA快−EMA慢，DEA=EMA(DIF)，柱=DIF−DEA。"""
    px = close.astype(float)
    f = max(2, int(fast))
    s = max(f + 1, int(slow))
    sig = max(1, int(signal))
    ema_f = px.ewm(span=f, adjust=False).mean()
    ema_s = px.ewm(span=s, adjust=False).mean()
    dif = ema_f - ema_s
    dea = dif.ewm(span=sig, adjust=False).mean()
    hist = dif - dea
    # 力度：|DIF−DEA|/收盘（无量纲相对强度）
    strength = (dif - dea).abs() / px.replace(0.0, pd.NA)
    golden = (dif > dea) & (dif.shift(1) <= dea.shift(1))
    death = (dif < dea) & (dif.shift(1) >= dea.shift(1))
    return pd.DataFrame(
        {
            "dif": dif,
            "dea": dea,
            "hist": hist,
            "strength": strength.fillna(0.0),
            "golden": golden.fillna(False),
            "death": death.fillna(False),
        },
        index=px.index,
    )


def classify_market_regime_macd_cross(
    close: pd.Series,
    *,
    macd_fast: int = DEFAULT_MACD_FAST,
    macd_slow: int = DEFAULT_MACD_SLOW,
    macd_signal: int = DEFAULT_MACD_SIGNAL,
    strength_min: float = 0.0,
) -> pd.Series:
    """MACD 金叉死叉粘性状态机（尾盘确认，与 MA 交叉同结构）。"""
    feat = macd_cross_features(
        close,
        fast=macd_fast,
        slow=macd_slow,
        signal=macd_signal,
    )
    return _sticky_from_crosses(
        feat["golden"],
        feat["death"],
        strength=feat["strength"],
        strength_min=strength_min,
    )


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
    strength_min: float = DEFAULT_REGIME_STRENGTH_MIN,
    slope_n: int = DEFAULT_REGIME_SLOPE_N,
    slope_weight: float = DEFAULT_REGIME_SLOPE_WEIGHT,
    macd_fast: int = DEFAULT_MACD_FAST,
    macd_slow: int = DEFAULT_MACD_SLOW,
    macd_signal: int = DEFAULT_MACD_SIGNAL,
    ma_n: int = DEFAULT_REGIME_MA_N,
    roc_n: int = DEFAULT_REGIME_ROC_N,
) -> pd.Series:
    """单票收盘价 → 牛/震/跌（当日确认，不含 shift）。"""
    m = str(method or DEFAULT_REGIME_METHOD).lower()
    if m in ("roc_ma", "ma60_roc", "legacy"):
        return classify_market_regime_roc_ma(close, ma_n=ma_n, roc_n=roc_n)
    if m in ("macd", "macd_cross"):
        return classify_market_regime_macd_cross(
            close,
            macd_fast=macd_fast,
            macd_slow=macd_slow,
            macd_signal=macd_signal,
            strength_min=strength_min,
        )
    return classify_market_regime_ma_cross(
        close,
        ma_fast=ma_fast,
        ma_slow=ma_slow,
        entangle_pct=entangle_pct,
        cross_lookback=cross_lookback,
        strength_min=strength_min,
        slope_n=slope_n,
        slope_weight=slope_weight,
    )


def build_market_regime_series(
    daily: pd.DataFrame,
    *,
    method: str | None = None,
    ma_fast: int = DEFAULT_REGIME_FAST,
    ma_slow: int = DEFAULT_REGIME_SLOW,
    entangle_pct: float = DEFAULT_REGIME_ENTANGLE_PCT,
    cross_lookback: int = DEFAULT_REGIME_CROSS_LOOKBACK,
    strength_min: float = DEFAULT_REGIME_STRENGTH_MIN,
    slope_n: int = DEFAULT_REGIME_SLOPE_N,
    slope_weight: float = DEFAULT_REGIME_SLOPE_WEIGHT,
    macd_fast: int = DEFAULT_MACD_FAST,
    macd_slow: int = DEFAULT_MACD_SLOW,
    macd_signal: int = DEFAULT_MACD_SIGNAL,
    ma_n: int = DEFAULT_REGIME_MA_N,
    roc_n: int = DEFAULT_REGIME_ROC_N,
) -> pd.DataFrame:
    """日线附加 regime_raw / regime_target / regime_exec（次日生效）。"""
    out = daily.copy()
    if "close" not in out.columns:
        raise KeyError("daily 缺少 close")
    method_l = str(method or DEFAULT_REGIME_METHOD).lower()
    raw = classify_market_regime(
        out["close"],
        method=method_l,
        ma_fast=ma_fast,
        ma_slow=ma_slow,
        entangle_pct=entangle_pct,
        cross_lookback=cross_lookback,
        strength_min=strength_min,
        slope_n=slope_n,
        slope_weight=slope_weight,
        macd_fast=macd_fast,
        macd_slow=macd_slow,
        macd_signal=macd_signal,
        ma_n=ma_n,
        roc_n=roc_n,
    )
    out["regime_raw"] = raw
    out["regime_target"] = raw
    out["regime_exec"] = raw.shift(1)
    out["bull_raw"] = (raw == REGIME_BULL).astype(float)
    out["bull_target"] = out["bull_raw"]
    out["bull_exec"] = out["bull_raw"].shift(1)
    if method_l in ("macd", "macd_cross"):
        feat = macd_cross_features(
            out["close"], fast=macd_fast, slow=macd_slow, signal=macd_signal
        )
        out["regime_strength"] = feat["strength"]
        out["regime_golden"] = feat["golden"]
        out["regime_death"] = feat["death"]
        out["regime_dif"] = feat["dif"]
        out["regime_dea"] = feat["dea"]
    elif method_l not in ("roc_ma", "ma60_roc", "legacy"):
        feat = ma_cross_strength(
            out["close"],
            ma_fast=ma_fast,
            ma_slow=ma_slow,
            slope_n=slope_n,
            slope_weight=slope_weight,
        )
        out["regime_spread"] = feat["spread"]
        out["regime_strength"] = feat["strength"]
        out["regime_golden"] = feat["golden"]
        out["regime_death"] = feat["death"]
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
    strength_min: float = DEFAULT_REGIME_STRENGTH_MIN,
    slope_n: int = DEFAULT_REGIME_SLOPE_N,
    slope_weight: float = DEFAULT_REGIME_SLOPE_WEIGHT,
    macd_fast: int = DEFAULT_MACD_FAST,
    macd_slow: int = DEFAULT_MACD_SLOW,
    macd_signal: int = DEFAULT_MACD_SIGNAL,
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
        strength_min=strength_min,
        slope_n=slope_n,
        slope_weight=slope_weight,
        macd_fast=macd_fast,
        macd_slow=macd_slow,
        macd_signal=macd_signal,
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
        "macd_fast": int(p.get("regime_macd_fast") or DEFAULT_MACD_FAST),
        "macd_slow": int(p.get("regime_macd_slow") or DEFAULT_MACD_SLOW),
        "macd_signal": int(p.get("regime_macd_signal") or DEFAULT_MACD_SIGNAL),
        "entangle_pct": float(
            p["regime_entangle_pct"]
            if p.get("regime_entangle_pct") is not None
            else DEFAULT_REGIME_ENTANGLE_PCT
        ),
        "cross_lookback": int(
            p.get("regime_cross_lookback") or DEFAULT_REGIME_CROSS_LOOKBACK
        ),
        "strength_min": float(
            p["regime_strength_min"]
            if p.get("regime_strength_min") is not None
            else DEFAULT_REGIME_STRENGTH_MIN
        ),
        "slope_n": int(p.get("regime_slope_n") or DEFAULT_REGIME_SLOPE_N),
        "slope_weight": float(
            p["regime_slope_weight"]
            if p.get("regime_slope_weight") is not None
            else DEFAULT_REGIME_SLOPE_WEIGHT
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
    elif method in ("macd", "macd_cross"):
        regime_line = (
            f"  · 行情三态（MACD{tp['macd_fast']}/{tp['macd_slow']}/{tp['macd_signal']} "
            f"尾盘金叉死叉粘性：金叉→牛至死叉，死叉→跌至金叉；次日开盘生效）\n"
        )
    else:
        regime_line = (
            f"  · 行情三态（MA{tp['ma_fast']}/MA{tp['ma_slow']} 尾盘交叉粘性："
            f"金叉→牛并保持至死叉；死叉→跌并保持至金叉；"
            f"力度=价差+{tp['slope_weight']:.1f}×顺势斜率（诊断"
            + (
                f"；切换门槛≥{tp['strength_min']*100:.1f}%"
                if float(tp["strength_min"]) > 0
                else "；默认交叉即切换"
            )
            + "）；收盘确认次日开盘生效）\n"
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
    "DEFAULT_MACD_FAST",
    "DEFAULT_MACD_SLOW",
    "DEFAULT_MACD_SIGNAL",
    "DEFAULT_REGIME_ENTANGLE_PCT",
    "DEFAULT_REGIME_CROSS_LOOKBACK",
    "DEFAULT_REGIME_STRENGTH_MIN",
    "DEFAULT_REGIME_SLOPE_N",
    "DEFAULT_REGIME_SLOPE_WEIGHT",
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
    "classify_market_regime_macd_cross",
    "classify_market_regime_roc_ma",
    "ma_cross_strength",
    "macd_cross_features",
    "bull_rules_text",
    "factor4_rules_text",
    "raw_to_bull_target",
    "resolve_factor4_tp_policy",
]
