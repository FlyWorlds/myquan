"""因子13 · 天通/凯盛风格孪生选股（大开大合 · 开盘突破亲和）。

仅用拟合窗口（默认 2020–2025）刻画种子票风格，再在截面找欧氏距离最近的票；
**不用 2026 走势参与选股**，样本外回测留给 2026。

经济含义（相对中证500/1000 池）：
  · 日震幅中等偏高
  · |收盘/开盘|≥2.5% 频次高（大开大合）
  · 日内触及开盘±2.5% 比例高（开盘突破可交易）
  · 日收益 |r|>3% 频次与年化波动中等偏高
  · 年内高低振幅中位不极端

得分 = −标准化特征到种子质心的欧氏距离（越高越像）。
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

DEFAULT_PARAMS: dict[str, Any] = {
    "fit_start": "2020-01-01",
    "fit_end": "2025-12-31",
    "seeds": ("sh600330", "sh600552"),
    "min_bars": 400,
    "break_pct": 0.025,
    "oc_big_pct": 0.025,
    "big_move_pct": 0.03,
    "top_k": 15,
    "mainboard_only": True,  # 只保留 60/00 主板，贴近种子
}

FEATURE_COLS: tuple[str, ...] = (
    "amp_mean",
    "oc_ge_2p5",
    "break_hit",
    "vol_ann",
    "big_move_freq",
    "yr_range_med",
)


def factor13_rules_text(params: dict[str, Any] | None = None) -> str:
    p = {**DEFAULT_PARAMS, **(params or {})}
    seeds = "、".join(p["seeds"])
    return f"""
================================================================================
  因子13 · 天通/凯盛风格孪生（大开大合 / 开盘突破亲和）
================================================================================
拟合窗：{p['fit_start']} → {p['fit_end']}（默认不含 2026）
种子：{seeds}
特征（全区间汇总，不做日频偷看）：
  1) amp_mean       日 (H-L)/C 均值 —— 震幅
  2) oc_ge_2p5      |C/O-1|≥{p['oc_big_pct']:.1%} 日占比 —— 大开大合
  3) break_hit      日内触及开盘±{p['break_pct']:.1%} 占比 —— 突破可交易性
  4) vol_ann        日收益年化波动
  5) big_move_freq  |日收益|≥{p['big_move_pct']:.0%} 占比
  6) yr_range_med   日历年 (max/min-1) 中位数 —— 大趋势弹性
打分：特征截面 z-score → 到种子质心欧氏距离 → score = −distance
选股：score 降序 TopK；可选仅主板（60/00）
用法：拟合窗末一次性选池，再在样本外（如 2026）跑策略一基线
================================================================================
"""


def _strip_tz(s: pd.Series) -> pd.Series:
    out = pd.to_datetime(s)
    if getattr(out.dt, "tz", None) is not None:
        out = out.dt.tz_localize(None)
    return out


def _is_mainboard(symbol: str) -> bool:
    s = str(symbol).lower()
    return s.startswith("sh60") or s.startswith("sz00")


def compute_style_features(
    daily: pd.DataFrame,
    *,
    fit_start: str,
    fit_end: str,
    min_bars: int = 400,
    break_pct: float = 0.025,
    oc_big_pct: float = 0.025,
    big_move_pct: float = 0.03,
) -> dict[str, float] | None:
    """单票拟合窗风格特征；数据不足返回 None。"""
    d = daily.copy()
    d["date"] = _strip_tz(d["date"])
    start = pd.Timestamp(fit_start)
    end = pd.Timestamp(fit_end)
    d = d[(d["date"] >= start) & (d["date"] <= end)].sort_values("date")
    if len(d) < int(min_bars):
        return None
    o = d["open"].astype(float)
    h = d["high"].astype(float)
    low = d["low"].astype(float)
    c = d["close"].astype(float)
    ret = c.pct_change()
    amp = (h - low) / c.replace(0.0, np.nan)
    oc = (c / o - 1.0).abs()
    up = h >= o * (1.0 + float(break_pct))
    dn = low <= o * (1.0 - float(break_pct))
    d2 = d.assign(_y=d["date"].dt.year, _c=c)
    yr = d2.groupby("_y")["_c"].agg(
        lambda s: float(s.max() / s.min() - 1.0) if float(s.min()) > 0 else np.nan
    )
    return {
        "n_bars": float(len(d)),
        "amp_mean": float(amp.mean()),
        "oc_ge_2p5": float((oc >= float(oc_big_pct)).mean()),
        "break_hit": float((up | dn).mean()),
        "vol_ann": float(ret.std() * np.sqrt(252)),
        "big_move_freq": float((ret.abs() >= float(big_move_pct)).mean()),
        "yr_range_med": float(yr.median()),
        "bh_ret": float(c.iloc[-1] / c.iloc[0] - 1.0),
        "bh_dd": float((c / c.cummax() - 1.0).min()),
    }


def style_feature_panel(
    dailies: dict[str, pd.DataFrame],
    *,
    params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    p = {**DEFAULT_PARAMS, **(params or {})}
    rows: list[dict[str, Any]] = []
    for sym, daily in dailies.items():
        feat = compute_style_features(
            daily,
            fit_start=str(p["fit_start"]),
            fit_end=str(p["fit_end"]),
            min_bars=int(p["min_bars"]),
            break_pct=float(p["break_pct"]),
            oc_big_pct=float(p["oc_big_pct"]),
            big_move_pct=float(p["big_move_pct"]),
        )
        if feat is None:
            continue
        feat["symbol"] = str(sym).lower()
        rows.append(feat)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("symbol").sort_index()


def score_style_twins(
    panel: pd.DataFrame,
    *,
    seeds: Sequence[str] | None = None,
    feature_cols: Sequence[str] = FEATURE_COLS,
) -> pd.DataFrame:
    """截面 z-score 后相对种子质心距离；附 sim_score = −dist。"""
    if panel.empty:
        return panel
    seeds = [str(s).lower() for s in (seeds or DEFAULT_PARAMS["seeds"])]
    cols = [c for c in feature_cols if c in panel.columns]
    out = panel.copy()
    mu = out[cols].mean()
    sd = out[cols].std(ddof=0).replace(0.0, np.nan)
    z = (out[cols] - mu) / sd
    present = [s for s in seeds if s in z.index]
    if not present:
        raise ValueError(f"种子不在特征面板中: {seeds}")
    centroid = z.loc[present].mean()
    dist = np.sqrt(((z - centroid) ** 2).sum(axis=1))
    out["dist"] = dist
    out["sim_score"] = -dist
    out["is_seed"] = out.index.isin(present)
    for c in cols:
        out[f"z_{c}"] = z[c]
    return out.sort_values("sim_score", ascending=False)


def select_twins(
    scored: pd.DataFrame,
    *,
    top_k: int = 15,
    mainboard_only: bool = True,
    exclude_seeds: bool = True,
    exclude_symbols: Iterable[str] | None = None,
) -> pd.DataFrame:
    df = scored.copy()
    if exclude_seeds and "is_seed" in df.columns:
        df = df.loc[~df["is_seed"].astype(bool)]
    ban = {str(x).lower() for x in (exclude_symbols or ())}
    if ban:
        df = df.loc[~df.index.isin(ban)]
    if mainboard_only:
        df = df.loc[[_is_mainboard(s) for s in df.index]]
    return df.sort_values("sim_score", ascending=False).head(int(top_k))


def factor13_signal(
    dailies: dict[str, pd.DataFrame] | None = None,
    *,
    panel: pd.DataFrame | None = None,
    params: dict[str, Any] | None = None,
    names: dict[str, str] | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """选股信号：返回打分表、TopK 名单与规则文本。"""
    p = {**DEFAULT_PARAMS, **(params or {})}
    if panel is None:
        if not dailies:
            raise ValueError("factor13_signal 需要 dailies 或 panel")
        panel = style_feature_panel(dailies, params=p)
    scored = score_style_twins(panel, seeds=p["seeds"])
    if names:
        scored = scored.copy()
        scored["name"] = [names.get(s, names.get(s.lower(), "")) for s in scored.index]
    picks = select_twins(
        scored,
        top_k=int(p["top_k"]),
        mainboard_only=bool(p["mainboard_only"]),
        exclude_seeds=True,
    )
    seed_rows = scored.loc[scored["is_seed"]] if "is_seed" in scored.columns else scored.iloc[0:0]
    return {
        "factor_id": "factor13",
        "params": p,
        "feature_cols": list(FEATURE_COLS),
        "scored": scored,
        "seeds": seed_rows,
        "picks": picks,
        "universe": list(picks.index),
        "rules_text": factor13_rules_text(p),
    }
