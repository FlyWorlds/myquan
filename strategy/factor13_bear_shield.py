"""因子13·熊市盾牌（月/季/年多尺度）。

理念：熊市要超额/防守；牛市不要求超额，但策略收益要有软性正贡献。
反过拟合默认：统一阈值、冻结宽松门槛、连续窗口稳定性过滤、严格时点选股。

尺度定义（BH 阈值可配）：
  · 年熊：BH < -5%
  · 季熊：BH < -5%
  · 年牛：BH ≥ +15%（软门槛 / 轻权重打分）

推荐默认 qy_blend / Top3 + thr* + stability：
  · 阈值：交易年 T 用 ≤T-1 在 {2%,2.5%,3%} 按夏普定 thr*；天通钉 ±3%
  · 年/季门槛宽松但冻结（不按 OOS 再调）
  · 软牛：年均策略≥5%；有牛年则牛年策略≥0
  · 稳定性：最近 L 个拟合年末均进入 Top pool，再按当年 score 取 Top3
  · 交易年 T：只用 ≤T-1 年信息选股（Walk-Forward）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]

# 暂时锁定：见 backtest/factor13_bear_shield/LOCKED.json；解锁前勿改 DEFAULT_PARAMS 门槛/TopK/thr*
_LOCK_PATH = _MYQUAN / "backtest" / "factor13_bear_shield" / "LOCKED.json"


def is_locked() -> bool:
    if not _LOCK_PATH.exists():
        return False
    try:
        import json

        return bool(json.loads(_LOCK_PATH.read_text(encoding="utf-8")).get("locked", False))
    except Exception:
        return False


THR_CANDIDATES: tuple[float, ...] = (0.02, 0.025, 0.03)

# 已知股性钉死（回测执行用；选股面板仍可用统一 thr）
PIN_THR: dict[str, float] = {
    "sh600330": 0.03,  # 天通
}

DEFAULT_PARAMS: dict[str, Any] = {
    "rule": "qy_blend",
    "top_k": 3,
    "fit_start_year": 2020,
    "own_bear_bh": -5.0,
    "own_bull_bh": 15.0,
    "quarter_bear_bh": -5.0,
    # 熊市门槛：宽松 + 冻结（反数据挖掘）
    "min_obear": 2,
    "min_obear_ret": -10.0,
    "min_obear_ex": 2.0,
    "min_obear_ex_floor": -10.0,
    "min_q_obear": 2,
    "min_q_ex": 0.0,
    # 软牛市
    "min_ret_mean": 0.0,
    "min_obull_ret": 0.0,
    "require_obull_if_any": True,
    "w_bull_score": 1.0,
    # 稳定性（反过拟合）
    "stability_lookback": 2,
    "stability_pool": 10,
    "stability_min_hits": 2,
    "min_obear_ex_sh": 8.0,
    "min_obear_hit": 0.5,
    "sharpe_lo": 0.3,
    "sharpe_hi": 1.8,
    "thr": 0.025,
    # 默认：个股 thr*（拟合窗夏普，PIT≤fit_end）；天通钉死见 pin_thr
    "use_per_stock_thr": True,
    "thr_candidates": THR_CANDIDATES,
    "pin_thr": PIN_THR,
    "mainboard_only": True,
}


def rules_text(params: dict[str, Any] | None = None) -> str:
    p = {**DEFAULT_PARAMS, **(params or {})}
    thr_note = "个股 thr*(拟合窗夏普)" if p.get("use_per_stock_thr") else f"统一 ±{float(p['thr'])*100:.1f}%"
    return f"""
================================================================================
  因子13 · 熊市盾牌（{p.get('rule')} / Top{p.get('top_k')}）· {thr_note}
================================================================================
反过拟合：门槛冻结；稳定性 Top{p.get('stability_pool')}×{p.get('stability_lookback')}窗≥{p.get('stability_min_hits')}；
交易年 T 仅用 ≤T-1。熊宽松 / 牛软：年均≥{p.get('min_ret_mean')}%
年熊 BH<{p['own_bear_bh']}%，季熊 BH<{p.get('quarter_bear_bh',-5)}%
池：中证500∪1000主板
================================================================================
"""


def resolve_trade_thr(symbol: str, params: dict[str, Any] | None = None) -> float:
    """回测执行阈值：钉死表优先，否则统一 thr。"""
    p = {**DEFAULT_PARAMS, **(params or {})}
    pin = {str(k).lower(): float(v) for k, v in (p.get("pin_thr") or {}).items()}
    sym = str(symbol).lower()
    if sym in pin:
        return float(pin[sym])
    return float(p.get("thr", 0.025))


def select_top_stable(
    year_panel: pd.DataFrame,
    *,
    fit_end_year: int = 2025,
    params: dict[str, Any] | None = None,
    k: int | None = None,
    exclude: set[str] | None = None,
    quarter_panel: pd.DataFrame | None = None,
    thr_map: dict[str, float] | None = None,
) -> pd.DataFrame:
    """稳定性选股：最近 L 个拟合年末进入 pool 的次数 ≥ min_hits，再按 fit_end score 取 TopK。"""
    p = {**DEFAULT_PARAMS, **(params or {})}
    top_k = int(k if k is not None else p["top_k"])
    lookback = int(p.get("stability_lookback", 2))
    pool = int(p.get("stability_pool", 12))
    min_hits = int(p.get("stability_min_hits", lookback))
    fit_start = int(p.get("fit_start_year", 2020))

    ends = [y for y in range(int(fit_end_year) - lookback + 1, int(fit_end_year) + 1) if y >= fit_start]
    if not ends:
        ends = [int(fit_end_year)]

    hit_count: dict[str, int] = {}
    latest: pd.DataFrame | None = None
    for ye in ends:
        # 每个窗口单独 thr_map（若开启），严格 ≤ ye
        tm = thr_map
        if tm is None and bool(p.get("use_per_stock_thr", False)):
            thr_df = fit_symbol_thresholds(
                year_panel,
                fit_start_year=fit_start,
                fit_end_year=int(ye),
                candidates=tuple(p.get("thr_candidates", THR_CANDIDATES)),
                pin=p.get("pin_thr", PIN_THR),
                mainboard_only=bool(p.get("mainboard_only", True)),
            )
            tm = dict(zip(thr_df["symbol"], thr_df["thr"])) if len(thr_df) else {}
        ranked = select_top(
            year_panel,
            fit_end_year=int(ye),
            params={**p, "top_k": pool},
            k=pool,
            exclude=exclude,
            quarter_panel=quarter_panel,
            thr_map=tm,
        )
        if ranked.empty:
            continue
        for sym in ranked["symbol"].astype(str).str.lower():
            hit_count[sym] = hit_count.get(sym, 0) + 1
        if ye == int(fit_end_year):
            latest = ranked

    if latest is None or latest.empty:
        return select_top(
            year_panel,
            fit_end_year=fit_end_year,
            params=p,
            k=top_k,
            exclude=exclude,
            quarter_panel=quarter_panel,
            thr_map=thr_map,
        )

    latest = latest.copy()
    latest["stab_hits"] = latest["symbol"].astype(str).str.lower().map(lambda s: hit_count.get(s, 0))
    latest["stab_lookback"] = lookback
    kept = latest[latest["stab_hits"] >= min_hits].copy()
    if kept.empty:
        # 回退：放宽到至少 1 次命中
        kept = latest[latest["stab_hits"] >= 1].copy()
    if kept.empty:
        kept = latest
    return kept.sort_values(["score", "stab_hits"], ascending=False).head(top_k).reset_index(drop=True)


def _pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(method="average", pct=True)


def _agg_bear(g: pd.DataFrame, bh_cut: float) -> dict[str, float]:
    bear = g[g["bh"] < bh_cut]

    def sm(x: pd.DataFrame, c: str) -> float:
        return float(x[c].mean()) if len(x) else float("nan")

    def hit(x: pd.DataFrame, c: str) -> float:
        return float((x[c] > 0).mean()) if len(x) else float("nan")

    return {
        "n_obear": int(len(bear)),
        "obear_ex": sm(bear, "excess"),
        "obear_ret": sm(bear, "ret"),
        "obear_hit": hit(bear, "excess"),
        "obear_ex_min": float(bear["excess"].min()) if len(bear) else float("nan"),
        "obear_dd_imp": sm(bear, "dd_improve"),
    }


def fit_symbol_thresholds(
    year_panel: pd.DataFrame,
    *,
    fit_start_year: int = 2020,
    fit_end_year: int = 2025,
    candidates: tuple[float, ...] | list[float] = THR_CANDIDATES,
    pin: dict[str, float] | None = None,
    mainboard_only: bool = True,
) -> pd.DataFrame:
    """拟合窗内按股选 thr*（夏普均值优先，其次收益均值）。返回 symbol,thr,fit_sharpe,fit_ret。"""
    pin = {str(k).lower(): float(v) for k, v in (pin or PIN_THR).items()}
    df = year_panel.copy()
    df["symbol"] = df["symbol"].astype(str).str.lower()
    df = df[(df["year"] >= int(fit_start_year)) & (df["year"] <= int(fit_end_year))]
    if mainboard_only and "mainboard" in df.columns:
        df = df[df["mainboard"].astype(int) == 1]
    # 只用显式阈值行（排除 thr_mode=best，避免同年重复）
    if "thr_mode" in df.columns:
        df = df[df["thr_mode"].astype(str) != "best"]
    df = df[df["thr"].astype(float).round(4).isin([round(float(t), 4) for t in candidates])]

    rows: list[dict] = []
    for sym, g0 in df.groupby("symbol"):
        sym = str(sym).lower()
        name = str(g0["name"].iloc[0]) if "name" in g0.columns else ""
        if sym in pin:
            thr_star = float(pin[sym])
            g = g0[np.isclose(g0["thr"].astype(float), thr_star)]
            rows.append(
                {
                    "symbol": sym,
                    "name": name,
                    "thr": thr_star,
                    "fit_sharpe": float(g["sharpe"].mean()) if len(g) else float("nan"),
                    "fit_ret": float(g["ret"].mean()) if len(g) else float("nan"),
                    "pinned": 1,
                }
            )
            continue
        cand_rows = []
        for thr in candidates:
            g = g0[np.isclose(g0["thr"].astype(float), float(thr))]
            if len(g) < 2:
                continue
            cand_rows.append(
                {
                    "thr": float(thr),
                    "fit_sharpe": float(g["sharpe"].mean()),
                    "fit_ret": float(g["ret"].mean()),
                    "n": int(len(g)),
                }
            )
        if not cand_rows:
            continue
        best = sorted(cand_rows, key=lambda x: (x["fit_sharpe"], x["fit_ret"]), reverse=True)[0]
        rows.append(
            {
                "symbol": sym,
                "name": name,
                "thr": float(best["thr"]),
                "fit_sharpe": float(best["fit_sharpe"]),
                "fit_ret": float(best["fit_ret"]),
                "pinned": 0,
            }
        )
    return pd.DataFrame(rows)


def panel_at_thr_map(year_panel: pd.DataFrame, thr_map: dict[str, float], default_thr: float = 0.025) -> pd.DataFrame:
    """按 thr_map 抽取每年一行；thr 列改写为 default_thr 以便下游统一过滤。"""
    df = year_panel.copy()
    df["symbol"] = df["symbol"].astype(str).str.lower()
    if "thr_mode" in df.columns:
        df = df[df["thr_mode"].astype(str) != "best"]
    parts = []
    for sym, g in df.groupby("symbol"):
        thr = float(thr_map.get(str(sym), default_thr))
        gg = g[np.isclose(g["thr"].astype(float), thr)].copy()
        if gg.empty:
            continue
        gg["thr"] = float(default_thr)
        gg["thr_mode"] = f"{default_thr:.3f}"
        gg["thr_used"] = thr
        parts.append(gg)
    if not parts:
        return df.iloc[0:0].copy()
    return pd.concat(parts, ignore_index=True)


def build_features(
    year_panel: pd.DataFrame,
    *,
    fit_end_year: int,
    params: dict[str, Any] | None = None,
    thr_map: dict[str, float] | None = None,
) -> pd.DataFrame:
    p = {**DEFAULT_PARAMS, **(params or {})}
    thr = float(p["thr"])
    bh_cut = float(p["own_bear_bh"])
    bull_cut = float(p.get("own_bull_bh", 15.0))
    fit_start = int(p.get("fit_start_year", 2020))
    df = year_panel.copy()
    df["symbol"] = df["symbol"].astype(str).str.lower()

    if thr_map:
        df = panel_at_thr_map(df, thr_map, default_thr=thr)
    elif "thr" in df.columns:
        df = df[np.isclose(df["thr"].astype(float), thr)]

    df = df[(df["year"] >= fit_start) & (df["year"] <= int(fit_end_year))]
    if bool(p.get("mainboard_only", True)) and "mainboard" in df.columns:
        df = df[df["mainboard"].astype(int) == 1]
    df = df.drop_duplicates(subset=["symbol", "year"], keep="last")

    rows: list[dict] = []
    for sym, g in df.groupby("symbol"):
        g = g.sort_values("year")
        avail = int(fit_end_year) - fit_start + 1
        if len(g) < min(3, avail):
            continue
        agg = _agg_bear(g, bh_cut)
        own_bull = g[g["bh"] >= bull_cut]
        thr_used = float(g["thr_used"].iloc[0]) if "thr_used" in g.columns else thr
        rows.append(
            {
                "symbol": str(sym).lower(),
                "name": str(g["name"].iloc[0]) if "name" in g.columns else "",
                "n_years": int(len(g)),
                "thr": thr_used,
                **agg,
                "n_obull": int(len(own_bull)),
                "obull_ex": float(own_bull["excess"].mean()) if len(own_bull) else float("nan"),
                "obull_ret": float(own_bull["ret"].mean()) if len(own_bull) else float("nan"),
                "ret_mean": float(g["ret"].mean()),
                "sharpe_mean": float(g["sharpe"].mean()),
                "ex_mean": float(g["excess"].mean()),
                "fit_end": int(fit_end_year),
            }
        )
    return pd.DataFrame(rows)


def build_quarter_features(
    quarter_panel: pd.DataFrame,
    *,
    fit_end_year: int,
    params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    p = {**DEFAULT_PARAMS, **(params or {})}
    bh_cut = float(p.get("quarter_bear_bh", -5.0))
    fit_start = int(p.get("fit_start_year", 2020))
    q = quarter_panel.copy()
    q["symbol"] = q["symbol"].astype(str).str.lower()
    if "kind" in q.columns:
        q = q[q["kind"] == "quarter"]
    q["year"] = q["period"].astype(str).str.slice(0, 4).astype(int)
    q = q[(q["year"] >= fit_start) & (q["year"] <= int(fit_end_year))]
    if bool(p.get("mainboard_only", True)) and "mainboard" in q.columns:
        q = q[q["mainboard"].astype(int) == 1]

    rows = []
    for sym, g in q.groupby("symbol"):
        agg = _agg_bear(g, bh_cut)
        rows.append(
            {
                "symbol": str(sym).lower(),
                "name": str(g["name"].iloc[0]) if "name" in g.columns else "",
                "q_n_obear": agg["n_obear"],
                "q_obear_ex": agg["obear_ex"],
                "q_obear_ret": agg["obear_ret"],
                "q_obear_hit": agg["obear_hit"],
                "q_obear_ex_min": agg["obear_ex_min"],
                "q_obear_dd_imp": agg["obear_dd_imp"],
            }
        )
    return pd.DataFrame(rows)


def _soft_bull_mask(r: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    """软牛市过滤：年均策略收益；有牛年则牛年策略均收益不低于下限。"""
    m = r["ret_mean"] >= float(p.get("min_ret_mean", 5.0))
    if bool(p.get("require_obull_if_any", True)):
        floor = float(p.get("min_obull_ret", 0.0))
        ok_bull = (r["n_obull"] <= 0) | (r["obull_ret"].fillna(floor) >= floor)
        m = m & ok_bull
    return m


def select_top(
    year_panel: pd.DataFrame,
    *,
    fit_end_year: int = 2025,
    params: dict[str, Any] | None = None,
    k: int | None = None,
    exclude: set[str] | None = None,
    quarter_panel: pd.DataFrame | None = None,
    thr_map: dict[str, float] | None = None,
) -> pd.DataFrame:
    p = {**DEFAULT_PARAMS, **(params or {})}
    if thr_map is None and bool(p.get("use_per_stock_thr", True)):
        thr_df = fit_symbol_thresholds(
            year_panel,
            fit_start_year=int(p.get("fit_start_year", 2020)),
            fit_end_year=int(fit_end_year),
            candidates=tuple(p.get("thr_candidates", THR_CANDIDATES)),
            pin=p.get("pin_thr", PIN_THR),
            mainboard_only=bool(p.get("mainboard_only", True)),
        )
        thr_map = dict(zip(thr_df["symbol"], thr_df["thr"])) if len(thr_df) else {}

    feat = build_features(year_panel, fit_end_year=fit_end_year, params=p, thr_map=thr_map)
    if feat.empty:
        return feat
    if exclude:
        feat = feat[~feat["symbol"].isin(exclude)]
    rule = str(p.get("rule", "qy_blend"))
    top_k = int(k if k is not None else p["top_k"])

    if rule == "qy_blend":
        if quarter_panel is None:
            qpath = _MYQUAN / "backtest" / "factor13_top10_quarterly" / "period_panel.parquet"
            if not qpath.exists():
                raise FileNotFoundError(f"qy_blend 需要季度面板: {qpath}")
            quarter_panel = pd.read_parquet(qpath)
        qf = build_quarter_features(quarter_panel, fit_end_year=fit_end_year, params=p)
        r = feat.merge(qf, on="symbol", how="inner", suffixes=("", "_q"))
        if "name_q" in r.columns:
            r["name"] = r["name"].fillna(r["name_q"])
        r = r[
            (r["n_obear"] >= int(p["min_obear"]))
            & (r["obear_ret"] >= float(p["min_obear_ret"]))
            & (r["obear_ex"] >= float(p["min_obear_ex"]))
            & (r["obear_ex_min"] >= float(p.get("min_obear_ex_floor", 0.0)))
            & (r["q_n_obear"] >= int(p.get("min_q_obear", 3)))
            & (r["q_obear_ex"] >= float(p.get("min_q_ex", 2.0)))
            & _soft_bull_mask(r, p)
        ].copy()
        if r.empty:
            return r
        # 牛年收益缺失时用年均收益填；牛市项轻权重（软约束，不抢熊市主分）
        bull_ret = r["obull_ret"].fillna(r["ret_mean"])
        w_bull = float(p.get("w_bull_score", 0.5))
        r["score"] = (
            3 * _pct_rank(r["obear_ex"])
            + 2 * _pct_rank(r["obear_ret"])
            + 2 * _pct_rank(r["q_obear_ex"])
            + 2 * _pct_rank(r["q_obear_hit"].fillna(0))
            + 2 * _pct_rank(r["obear_ex_min"])
            + w_bull * _pct_rank(r["ret_mean"])
            + w_bull * _pct_rank(bull_ret)
        )
    elif rule in ("bear_abs_pos", "bear_abs_pos_floor"):
        r = feat[
            (feat["n_obear"] >= int(p["min_obear"]))
            & (feat["obear_ret"] >= float(p["min_obear_ret"]))
            & (feat["obear_ex"] >= float(p["min_obear_ex"]))
            & _soft_bull_mask(feat, p)
        ].copy()
        if rule == "bear_abs_pos_floor":
            r = r[r["obear_ex_min"] >= float(p.get("min_obear_ex_floor", 0.0))]
        if r.empty:
            return r
        if rule == "bear_abs_pos_floor":
            r["score"] = (
                3 * _pct_rank(r["obear_ret"])
                + 3 * _pct_rank(r["obear_ex"])
                + 2 * _pct_rank(r["obear_ex_min"])
                + 1 * _pct_rank(r["obear_dd_imp"])
                + 1 * _pct_rank(r["ret_mean"])
            )
        else:
            r["score"] = (
                3 * _pct_rank(r["obear_ret"])
                + 3 * _pct_rank(r["obear_ex"])
                + 1 * _pct_rank(r["obear_dd_imp"])
                + 1 * _pct_rank(r["ret_mean"])
            )
    elif rule == "bear_ex_sh":
        r = feat[
            (feat["n_obear"] >= int(p["min_obear"]))
            & (feat["obear_ex"] >= float(p["min_obear_ex_sh"]))
            & (feat["obear_hit"] >= float(p["min_obear_hit"]))
            & (feat["sharpe_mean"].between(float(p["sharpe_lo"]), float(p["sharpe_hi"])))
            & _soft_bull_mask(feat, p)
        ].copy()
        if r.empty:
            return r
        r["score"] = (
            3 * _pct_rank(r["obear_ex"])
            + 2 * _pct_rank(r["obear_hit"])
            + 1 * _pct_rank(r["sharpe_mean"])
            + 1 * _pct_rank(r["obear_dd_imp"])
            + 1 * _pct_rank(r["ret_mean"])
        )
    else:
        raise ValueError(f"unknown rule: {rule}")

    return r.sort_values("score", ascending=False).head(top_k).reset_index(drop=True)
