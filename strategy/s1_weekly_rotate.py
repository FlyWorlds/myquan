"""策略十三核心：策略1 质量带宇宙 · 周频动量轮动 · 重叠票留仓。

规则：
  · 宇宙：策略1 宽宇宙主板（剔科创/创业/北交/ST/收盘≥100）
  · 资格：因子13A 质量带（上年面板；参数复用 s1_f13_refit best）
  · 信号：本周最后交易日，在资格池内按近 mom_n 日涨幅取 TopK
  · 持有：下一周等权；仍在名单内的票不强制换出（部分不换）
  · 成交：一字涨停开盘买不进；一字跌停封单卖不出

研究模拟，不构成投资建议。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from strategy.costs import COST_ROUND_TRIP, FEE_ROUND_TRIP
from strategy.factor13_fit import apply_quality_filters, enrich_cross_section_scores
from strategy.near_high_hold import (
    daily_from_snaps_fill,
    limit_fill_masks,
)

_MYQUAN = Path(__file__).resolve().parents[1]
PANEL_CSV = _MYQUAN / "backtest" / "s1_f13_refit_2025" / "year_thr_panel_mainboard.csv"
SUMMARY_JSON = _MYQUAN / "backtest" / "s1_f13_refit_2025" / "summary.json"
WIDE_CACHE = _MYQUAN / "backtest" / "universe_wide" / "daily_cache"
ZZ_CACHE = _MYQUAN / "backtest" / "universe_zz500_1000" / "daily_cache"
WIDE_META = _MYQUAN / "backtest" / "universe_wide" / "results.csv"

DEFAULT_PARAMS: dict[str, Any] = {
    "top_k": 20,
    "mom_n": 20,
    "max_price": 100.0,
    "candidate_pool": 80,
    "start": "20250102",
    "end": "20260831",
    "apply_cost": True,
}


def _is_st_name(name: str) -> bool:
    n = str(name).strip().upper()
    return "ST" in n or n.startswith("*")


def _is_mainboard_sym(sym: str) -> bool:
    s = str(sym).lower()
    return s.startswith("sh60") or s.startswith("sz00")


def load_f13_rule() -> dict[str, Any]:
    if SUMMARY_JSON.exists():
        prev = json.loads(SUMMARY_JSON.read_text(encoding="utf-8"))
        cfg = dict(prev.get("factor13_best") or {})
        return {
            "thr_mode": str(cfg.get("thr_mode") or "best"),
            "min_sharpe": float(cfg.get("sharpe_lo", 0.7)),
            "max_sharpe": float(cfg.get("sharpe_hi", 2.2)),
            "mdd_lo": float(cfg.get("mdd_lo", 20.0)),
            "mdd_hi": float(cfg.get("mdd_hi", 32.0)),
            "dd_ratio_max": float(cfg.get("dd_ratio_max", 0.7)),
            "rank_col": str(cfg.get("rank_col") or "excess"),
        }
    return {
        "thr_mode": "best",
        "min_sharpe": 0.7,
        "max_sharpe": 2.2,
        "mdd_lo": 20.0,
        "mdd_hi": 32.0,
        "dd_ratio_max": 0.7,
        "rank_col": "excess",
    }


def s1_weekly_rules_text(params: dict[str, Any] | None = None) -> str:
    p = {**DEFAULT_PARAMS, **(params or {})}
    rule = load_f13_rule()
    return f"""
================================================================================
策略十三 · 策略1质量带周频轮动
================================================================================
宇宙：沪深300∪500∪1000∪1500 主板；剔 ST、收盘≥{p['max_price']:.0f}元、科创/创业/北交
资格：因子13A 质量带（上年；thr={rule['thr_mode']} 夏普[{rule['min_sharpe']},{rule['max_sharpe']}]
      回撤[{rule['mdd_lo']},{rule['mdd_hi']}] dd≤{rule['dd_ratio_max']}）初选≤{p['candidate_pool']}
信号：本周收盘，资格池内近 {p['mom_n']} 日涨幅 Top{p['top_k']}
持有：下一周等权；仍在 Top{p['top_k']} 的票不强制换出（部分不换）
成交：一字涨停开盘买不进；一字跌停封单卖不出；费率 COST_ROUND_TRIP≈{COST_ROUND_TRIP*100:.3f}%
参考策略一选股链，执行改为周频轮动持有（非开盘突破单票）。
研究模拟，不构成投资建议。
================================================================================
""".strip()


def _name_map() -> dict[str, str]:
    if not WIDE_META.exists():
        return {}
    meta = pd.read_csv(WIDE_META, dtype=str)
    meta["symbol"] = meta["symbol"].astype(str).str.lower()
    return meta.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()


def quality_candidates_by_year(
    panel: pd.DataFrame,
    rule: dict[str, Any],
    *,
    candidate_pool: int,
) -> dict[int, list[str]]:
    """fit_year → 资格 symbol 列表（主板、非 ST）。"""
    names = _name_map()
    out: dict[int, list[str]] = {}
    thr = str(rule["thr_mode"])
    rank_col = str(rule.get("rank_col") or "excess")
    for y in sorted(panel["year"].unique()):
        ydf = panel[(panel["year"] == int(y)) & (panel["thr_mode"] == thr)].copy()
        if ydf.empty:
            ydf = panel[(panel["year"] == int(y)) & (panel["thr_mode"] == "best")].copy()
        if ydf.empty:
            continue
        scored = enrich_cross_section_scores(ydf)
        filt = apply_quality_filters(scored, rule)
        if len(filt) < candidate_pool:
            loose = scored[
                (scored["sharpe"] >= max(0.3, float(rule["min_sharpe"]) - 0.3))
                & (scored["dd_ratio"] <= float(rule["dd_ratio_max"]) + 0.1)
                & (scored.get("mainboard", 1) == 1)
            ].sort_values(rank_col, ascending=False)
            merged = pd.concat([filt, loose], ignore_index=True).drop_duplicates("symbol")
        else:
            merged = filt.sort_values(rank_col, ascending=False)
        syms: list[str] = []
        for s in merged["symbol"].astype(str).str.lower().tolist():
            if not _is_mainboard_sym(s):
                continue
            if _is_st_name(names.get(s, "")):
                continue
            syms.append(s)
            if len(syms) >= candidate_pool:
                break
        out[int(y)] = syms
    return out


def _load_close_panel(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    frames: dict[str, pd.Series] = {}
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    for sym in symbols:
        path = WIDE_CACHE / f"{sym}_daily_qfq.parquet"
        if not path.exists():
            path = ZZ_CACHE / f"{sym}_daily_qfq.parquet"
        if not path.exists():
            continue
        d = pd.read_parquet(path, columns=["date", "close"])
        if d.empty:
            continue
        idx = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
        s = pd.Series(pd.to_numeric(d["close"], errors="coerce").to_numpy(), index=idx)
        s = s[~s.index.duplicated(keep="last")].sort_index()
        s = s[(s.index >= start_ts - pd.Timedelta(days=120)) & (s.index <= end_ts)]
        if len(s) < 40:
            continue
        frames[sym] = s
    if not frames:
        return pd.DataFrame()
    close = pd.DataFrame(frames).sort_index()
    return close.loc[(close.index >= start_ts - pd.Timedelta(days=90)) & (close.index <= end_ts)]


def _load_ohlc_panel(symbols: list[str], start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    closes: dict[str, pd.Series] = {}
    opens: dict[str, pd.Series] = {}
    highs: dict[str, pd.Series] = {}
    lows: dict[str, pd.Series] = {}
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    for sym in symbols:
        path = WIDE_CACHE / f"{sym}_daily_qfq.parquet"
        if not path.exists():
            path = ZZ_CACHE / f"{sym}_daily_qfq.parquet"
        if not path.exists():
            continue
        d = pd.read_parquet(path)
        if d.empty or "close" not in d.columns:
            continue
        idx = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
        d = d.copy()
        d.index = idx
        d = d[~d.index.duplicated(keep="last")].sort_index()
        d = d[(d.index >= start_ts - pd.Timedelta(days=120)) & (d.index <= end_ts)]
        if len(d) < 40:
            continue
        closes[sym] = pd.to_numeric(d["close"], errors="coerce")
        opens[sym] = pd.to_numeric(d.get("open", d["close"]), errors="coerce")
        highs[sym] = pd.to_numeric(d.get("high", d["close"]), errors="coerce")
        lows[sym] = pd.to_numeric(d.get("low", d["close"]), errors="coerce")
    if not closes:
        empty = pd.DataFrame()
        return empty, empty, empty, empty
    close = pd.DataFrame(closes).sort_index()
    open_px = pd.DataFrame(opens).reindex_like(close)
    high = pd.DataFrame(highs).reindex_like(close)
    low = pd.DataFrame(lows).reindex_like(close)
    mask = (close.index >= start_ts - pd.Timedelta(days=90)) & (close.index <= end_ts)
    return close.loc[mask], open_px.loc[mask], high.loc[mask], low.loc[mask]


def _fit_year_for_signal(sig: pd.Timestamp) -> int:
    """信号日用已完整结束的日历年面板。"""
    return int(sig.year) - 1


def build_weekly_snap(
    close: pd.DataFrame,
    cand_by_year: dict[int, list[str]],
    *,
    top_k: int,
    mom_n: int,
    max_price: float,
    start: str,
    end: str,
) -> tuple[dict[pd.Timestamp, set[str]], pd.DataFrame]:
    """本周收盘选股 → snap[下周周一] = picks；返回 weekly picks 表。"""
    idx = close.index
    week_ends = idx.to_series().groupby(idx.to_period("W-FRI")).max()
    week_ends = pd.DatetimeIndex(week_ends.values).normalize()
    week_ends = week_ends[(week_ends >= pd.Timestamp(start) - pd.Timedelta(days=14)) & (week_ends <= pd.Timestamp(end))]
    mom = close / close.shift(int(mom_n)) - 1.0
    rows: list[dict[str, Any]] = []
    snap: dict[pd.Timestamp, set[str]] = {}
    prev_picks: set[str] = set()
    for sig in week_ends:
        if sig not in close.index:
            continue
        fit_y = _fit_year_for_signal(sig)
        cands = [s for s in cand_by_year.get(fit_y, []) if s in close.columns]
        if not cands:
            # 回退：用更早一年
            for y in range(fit_y - 1, fit_y - 4, -1):
                cands = [s for s in cand_by_year.get(y, []) if s in close.columns]
                if cands:
                    break
        if not cands:
            continue
        px = close.loc[sig, cands]
        ok_price = px[px < float(max_price)].dropna().index.tolist()
        if not ok_price:
            continue
        scores = mom.loc[sig, ok_price].dropna().sort_values(ascending=False)
        picks = scores.head(int(top_k)).index.astype(str).tolist()
        if not picks:
            continue
        # 下一周生效：信号日之后的下一个周一
        days_ahead = (7 - int(sig.dayofweek)) % 7
        if days_ahead == 0:
            days_ahead = 7
        hold_week = (sig + pd.Timedelta(days=days_ahead)).normalize()
        snap[hold_week] = set(picks)
        kept = sorted(set(picks) & prev_picks)
        added = sorted(set(picks) - prev_picks)
        dropped = sorted(prev_picks - set(picks))
        rows.append(
            {
                "signal_date": sig.strftime("%Y-%m-%d"),
                "hold_week": hold_week.strftime("%Y-%m-%d"),
                "fit_year": fit_y,
                "n": len(picks),
                "n_kept": len(kept),
                "n_added": len(added),
                "n_dropped": len(dropped),
                "turn": (1.0 - len(kept) / max(len(picks), 1)),
                "picks": ",".join(picks),
                "kept": ",".join(kept),
                "added": ",".join(added),
                "dropped": ",".join(dropped),
            }
        )
        prev_picks = set(picks)
    return snap, pd.DataFrame(rows)


@dataclass
class S1WeeklyRotateResult:
    nav: pd.Series
    daily_ret: pd.Series
    stats: dict[str, float]
    monthly: pd.DataFrame
    weekly_picks: pd.DataFrame
    config: dict[str, Any]
    fill_stats: dict[str, Any] = field(default_factory=dict)


def _period_return(nav: pd.Series, start: str, end: str) -> float:
    s = nav.loc[start:end]
    if len(s) < 2:
        return float("nan")
    return float(s.iloc[-1] / s.iloc[0] - 1.0) * 100.0


def _metrics(daily: pd.Series) -> dict[str, float]:
    d = daily.dropna()
    if d.empty:
        return {"ret_pct": float("nan"), "sharpe": float("nan"), "mdd_pct": float("nan")}
    nav = (1.0 + d).cumprod()
    ret = float(nav.iloc[-1] / nav.iloc[0] - 1.0) * 100.0
    vol = float(d.std() * np.sqrt(252)) if len(d) > 2 else float("nan")
    sharpe = float(d.mean() / d.std() * np.sqrt(252)) if d.std() > 1e-12 else float("nan")
    peak = nav.cummax()
    mdd = float((nav / peak - 1.0).min() * 100.0)
    return {"ret_pct": ret, "sharpe": sharpe, "mdd_pct": mdd, "vol_pct": vol * 100.0 if np.isfinite(vol) else float("nan")}


def run_s1_weekly_rotate(**kwargs: Any) -> S1WeeklyRotateResult:
    p = {**DEFAULT_PARAMS, **kwargs}
    rule = load_f13_rule()
    if not PANEL_CSV.exists():
        raise FileNotFoundError(f"缺少面板 {PANEL_CSV}")
    panel = pd.read_csv(PANEL_CSV)
    panel["symbol"] = panel["symbol"].astype(str).str.lower()
    cand_by_year = quality_candidates_by_year(
        panel, rule, candidate_pool=int(p["candidate_pool"])
    )
    all_syms = sorted({s for xs in cand_by_year.values() for s in xs})
    close, open_px, high, low = _load_ohlc_panel(all_syms, str(p["start"]), str(p["end"]))
    if close.empty:
        raise RuntimeError("无可用日线缓存，请先跑 s1_f13_refit_2025 --fetch-missing")

    snap, weekly = build_weekly_snap(
        close,
        cand_by_year,
        top_k=int(p["top_k"]),
        mom_n=int(p["mom_n"]),
        max_price=float(p["max_price"]),
        start=str(p["start"]),
        end=str(p["end"]),
    )
    # 截到回测窗口
    close_bt = close.loc[str(p["start"]) : str(p["end"])]
    open_bt = open_px.reindex_like(close_bt)
    high_bt = high.reindex_like(close_bt)
    low_bt = low.reindex_like(close_bt)
    block_buy, block_sell, _ = limit_fill_masks(close_bt, open_bt, high_bt, low_bt)
    daily, fill = daily_from_snaps_fill(close_bt, snap, block_buy, block_sell)

    # 换手成本：按周 turn 扣 COST_ROUND_TRIP * turn（部分不换则 turn 低）
    if bool(p.get("apply_cost", True)) and not weekly.empty:
        turn_map = {
            pd.Timestamp(r.hold_week): float(r.turn) for r in weekly.itertuples(index=False)
        }
        cost_daily = daily.copy() * 0.0
        wkey = close_bt.index - pd.to_timedelta(close_bt.index.dayofweek, unit="D")
        seen: set[pd.Timestamp] = set()
        for i, w in enumerate(wkey):
            ww = pd.Timestamp(w).normalize()
            if ww in seen:
                continue
            seen.add(ww)
            t = turn_map.get(ww)
            if t is None or not np.isfinite(t):
                continue
            # 周一扣费（或该周第一根）
            cost_daily.iloc[i] -= float(t) * COST_ROUND_TRIP
        daily = daily + cost_daily

    nav = (1.0 + daily.fillna(0.0)).cumprod()
    stats = _metrics(daily.loc[str(p["start"]) : str(p["end"])])
    # 月度
    mnav = nav.resample("ME").last().dropna()
    mret = mnav.pct_change() * 100.0
    monthly = pd.DataFrame(
        {
            "month": mnav.index.strftime("%Y-%m"),
            "nav": mnav.values,
            "ret_pct": mret.values,
        }
    )
    aug = _period_return(nav, "2026-08-01", "2026-08-31")
    stats["aug_2026_pct"] = aug
    stats["avg_week_turn"] = float(weekly["turn"].mean()) if not weekly.empty else float("nan")
    stats["avg_kept"] = float(weekly["n_kept"].mean()) if not weekly.empty else float("nan")
    return S1WeeklyRotateResult(
        nav=nav,
        daily_ret=daily,
        stats=stats,
        monthly=monthly,
        weekly_picks=weekly,
        config={**p, "factor13_rule": rule},
        fill_stats=fill,
    )
