"""概念龙头股评分：因子13质量带 + 因子1 + 缠论笔盈亏比（OOS 2025至今）。

打分与排序复用 ``backtest/ai_concept_f1_f13_report.py``：
  · 定参 FIT（2020–2023）截面 ``score_quality`` + 质量带硬过滤
  · 样本外 OOS（2025→今）展示收益/超额/回撤/盈亏比/胜率
  · 缠论笔盈亏比（策略七）在 OOS 窗单独计算，作对照列
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backtest.ai_concept_f1_f13_report import (  # noqa: E402
    FIT_END,
    FIT_START,
    MIN_BARS,
    OOS_START,
    THR,
    _today_ymd,
    _to_symbol,
    eval_window,
    fetch_one,
)
from strategy.factor13_fit import enrich_cross_section_scores, load_best_rule

from .concept_leaders import _stock_name_map
from .live import member_codes_for_concept

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"

DEFAULT_START = "2025-01-01"
TOP_N = 5
MAX_CANDIDATES = 60
MIN_OOS_TRADES = 3
FETCH_WORKERS = 8


def _iso_to_ymd(s: str) -> str:
    return str(s).replace("-", "")[:8]


def _ymd_to_iso(s: str) -> str:
    t = str(s).replace("-", "")[:8]
    return f"{t[:4]}-{t[4:6]}-{t[6:8]}"


def _f13_pass_mask(scored: pd.DataFrame, rule: dict[str, Any]) -> pd.Series:
    """与 ai_concept_f1_f13_report 一致的质量带硬过滤。"""
    bands = rule.get("fill_bands") or [
        {
            "min_sharpe": rule.get("min_sharpe"),
            "max_sharpe": rule.get("max_sharpe"),
            "mdd_lo": rule.get("mdd_lo"),
            "mdd_hi": rule.get("mdd_hi"),
            "dd_ratio_max": rule.get("dd_ratio_max"),
        }
    ]
    pass_mask = pd.Series(False, index=scored.index)
    for band in bands:
        m = pd.Series(True, index=scored.index)
        if band.get("min_sharpe") is not None:
            m &= scored["sharpe"] >= float(band["min_sharpe"])
        if band.get("max_sharpe") is not None:
            m &= scored["sharpe"] <= float(band["max_sharpe"])
        if band.get("mdd_lo") is not None:
            m &= scored["mdd"] >= float(band["mdd_lo"])
        if band.get("mdd_hi") is not None:
            m &= scored["mdd"] <= float(band["mdd_hi"])
        if band.get("dd_ratio_max") is not None:
            m &= (scored["dd_ratio"] <= float(band["dd_ratio_max"])) & (scored["bh_dd"] > 5)
        if int(m.sum()) >= int(rule.get("top_k", 10)):
            pass_mask = m
            break
        pass_mask = pass_mask | m
    return pass_mask


def _chan_oos_metrics(
    daily: pd.DataFrame,
    *,
    code: str,
    name: str,
    oos_start: str,
    oos_end: str,
) -> dict[str, Any]:
    try:
        from backtest.ai_concept_f1_f13_report import _slice_daily
        from strategy.bi_pl_ratio import analyze_bi_pl_ratio

        sub = _slice_daily(daily, oos_start, oos_end)
        if sub is None or len(sub) < 30:
            return {}
        sym = _to_symbol(code)
        if not sym:
            return {}
        res = analyze_bi_pl_ratio(
            sub,
            symbol=sym,
            symbol_name=name,
            entry_pct=THR,
            max_bi_num=300,
            out_dir=None,
        )
        s = res.summary or {}
        return {
            "chan_pl_ratio": s.get("pl_ratio"),
            "chan_win_rate": s.get("win_rate_net"),
            "chan_trades": s.get("n_trades"),
            "chan_compound_pct": s.get("factor1_compound_net_pct"),
        }
    except Exception:
        return {}


def _eval_one_stock(
    code: str,
    name: str,
    daily: pd.DataFrame,
    oos_end: str,
    *,
    oos_start: str = OOS_START,
) -> dict[str, Any] | None:
    symbol = _to_symbol(code)
    if not symbol:
        return None
    fit = eval_window(daily, FIT_START, FIT_END)
    oos = eval_window(daily, oos_start, oos_end)
    if int(fit.get("n_bars") or 0) < MIN_BARS:
        return None
    chan = _chan_oos_metrics(
        daily, code=code, name=name, oos_start=oos_start, oos_end=oos_end
    )
    dd_ratio = (
        fit["mdd"] / fit["bh_dd"]
        if fit.get("bh_dd") and fit["bh_dd"] > 0
        else np.nan
    )
    return {
        "code": str(code).zfill(6),
        "name": name or code,
        "symbol": symbol,
        "dd_ratio": dd_ratio,
        "fit_ret": fit["ret"],
        "fit_mdd": fit["mdd"],
        "fit_sharpe": fit["sharpe"],
        "fit_bh_ret": fit["bh_ret"],
        "fit_bh_dd": fit["bh_dd"],
        "fit_excess": fit["excess"],
        "fit_dd_improve": fit["dd_improve"],
        "fit_pl_ratio": fit["pl_ratio"],
        "fit_win_rate": fit["win_rate"],
        "fit_n_bars": fit["n_bars"],
        "oos_ret": oos["ret"],
        "oos_mdd": oos["mdd"],
        "oos_sharpe": oos["sharpe"],
        "oos_excess": oos["excess"],
        "oos_pl_ratio": oos["pl_ratio"],
        "oos_win_rate": oos["win_rate"],
        "oos_profit_factor": oos["profit_factor"],
        "oos_n_trades": oos["n_trades"],
        "oos_n_bars": oos["n_bars"],
        **chan,
    }


def _rank_pool(df: pd.DataFrame, *, top_n: int) -> pd.DataFrame:
    """因子13通过优先，组内按 OOS 盈亏比 / 利润因子 / score_quality 排序。"""
    ranked = df.copy()
    ranked["oos_pl_ratio"] = pd.to_numeric(ranked["oos_pl_ratio"], errors="coerce")
    ranked["score_quality"] = pd.to_numeric(ranked["score_quality"], errors="coerce")
    ranked = ranked[ranked["oos_n_trades"].fillna(0) >= MIN_OOS_TRADES]
    ranked = ranked[ranked["fit_n_bars"].fillna(0) >= MIN_BARS]
    pool = ranked[ranked["f13_pass"] == 1].copy()
    if len(pool) < top_n:
        extra = ranked[ranked["f13_pass"] != 1].sort_values(
            "score_quality", ascending=False, na_position="last"
        )
        need = max(top_n * 4, 20) - len(pool)
        pool = pd.concat([pool, extra.head(max(0, need))], ignore_index=True)
    return pool.sort_values(
        by=["f13_pass", "oos_pl_ratio", "oos_profit_factor", "score_quality"],
        ascending=[False, False, False, False],
        na_position="last",
    ).head(top_n)


def rank_concept_leaders(
    concept_name: str,
    *,
    start: str = DEFAULT_START,
    end: str | None = None,
    top_n: int = TOP_N,
    max_candidates: int = MAX_CANDIDATES,
) -> dict[str, Any]:
    """概念成分股：因子13 + 因子1 + 缠论，取 TopN。"""
    oos_end = _iso_to_ymd(end) if end else _today_ymd()
    oos_start = _iso_to_ymd(start)
    codes = member_codes_for_concept(concept_name, limit=max_candidates)
    names = _stock_name_map()
    if not codes:
        return {
            "concept": concept_name,
            "start": _ymd_to_iso(oos_start),
            "end": _ymd_to_iso(oos_end),
            "leaders": [],
            "error": "无成分股",
        }

    daily_map: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        futs = {
            pool.submit(fetch_one, _to_symbol(c) or "", oos_end, cache_only=False): c
            for c in codes
            if _to_symbol(c)
        }
        for fut in as_completed(futs):
            sym, df, st = fut.result()
            if st == "ok" and df is not None:
                daily_map[sym] = df

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        futs = []
        for c in codes:
            sym = _to_symbol(c)
            if not sym or sym not in daily_map:
                continue
            futs.append(
                pool.submit(
                    _eval_one_stock,
                    c,
                    names.get(c, c),
                    daily_map[sym],
                    oos_end,
                    oos_start=oos_start,
                )
            )
        for fut in as_completed(futs):
            row = fut.result()
            if row:
                rows.append(row)

    if not rows:
        return {
            "concept": concept_name,
            "start": _ymd_to_iso(oos_start),
            "end": _ymd_to_iso(oos_end),
            "leaders": [],
            "error": "样本不足或日线不可用",
        }

    ok = pd.DataFrame(rows)
    rule = {**load_best_rule(), "mainboard_only": False}
    scored = ok.rename(
        columns={
            "fit_ret": "ret",
            "fit_mdd": "mdd",
            "fit_sharpe": "sharpe",
            "fit_bh_ret": "bh_ret",
            "fit_bh_dd": "bh_dd",
            "fit_excess": "excess",
            "fit_dd_improve": "dd_improve",
        }
    )
    scored = enrich_cross_section_scores(scored)
    scored["f13_pass"] = _f13_pass_mask(scored, rule).astype(int)
    merge_cols = ["code", "score_quality", "score_fit", "score_esd", "f13_pass"]
    ok = ok.merge(scored[merge_cols], on="code", how="left")

    top = _rank_pool(ok, top_n=top_n)

    def _f(v: Any, nd: int = 2) -> float | None:
        try:
            x = float(v)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(x):
            return None
        return round(x, nd)

    leaders: list[dict[str, Any]] = []
    for rank, (_, r) in enumerate(top.iterrows(), start=1):
        chan_wr = r.get("chan_win_rate")
        leaders.append(
            {
                "rank": rank,
                "code": str(r["code"]),
                "name": str(r.get("name") or r["code"]),
                "score_quality": _f(r.get("score_quality"), 4),
                "f13_pass": bool(int(r.get("f13_pass") or 0) == 1),
                "pl_ratio": _f(r.get("oos_pl_ratio"), 3),
                "win_rate": _f(r.get("oos_win_rate"), 2),
                "profit_factor": _f(r.get("oos_profit_factor"), 3),
                "excess_pct": _f(r.get("oos_excess"), 2),
                "mdd_pct": _f(r.get("oos_mdd"), 2),
                "ret_pct": _f(r.get("oos_ret"), 2),
                "sharpe_fit": _f(r.get("fit_sharpe"), 3),
                "n_trades": int(r.get("oos_n_trades") or 0),
                "chan_pl_ratio": _f(r.get("chan_pl_ratio"), 3),
                "chan_win_rate": _f(float(chan_wr) * 100, 2)
                if chan_wr is not None and chan_wr == chan_wr
                else None,
                "chan_trades": int(r.get("chan_trades") or 0),
            }
        )

    return {
        "concept": concept_name,
        "start": _ymd_to_iso(oos_start),
        "end": _ymd_to_iso(oos_end),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "scoring": {
            "source": "backtest/ai_concept_f1_f13_report.py",
            "quality": "因子13质量带（FIT 2020-2023 截面 score_quality + 硬过滤）",
            "factor1": f"策略一因子1（开盘±{THR*100:.1f}%，OOS 窗盈亏比/胜率/收益）",
            "chan": "策略七缠论笔盈亏比（OOS 窗对照）",
            "rank": "F13通过优先 → OOS盈亏比 → 利润因子 → score_quality",
        },
        "candidate_count": len(rows),
        "leaders": leaders,
    }


def _cache_path(concept: str) -> Path:
    safe = concept.replace("/", "_").replace("\\", "_")
    return CACHE_DIR / f"leader_score_{safe}.json"


def get_concept_scored_leaders(
    concept_name: str,
    *,
    start: str = DEFAULT_START,
    end: str | None = None,
    top_n: int = TOP_N,
    force: bool = False,
) -> dict[str, Any]:
    cache = _cache_path(concept_name)
    end_iso = end or _ymd_to_iso(_today_ymd())
    if cache.is_file() and not force:
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if (
                cached.get("start") == start
                and cached.get("end", "")[:10] == end_iso[:10]
                and cached.get("leaders")
            ):
                return cached
        except Exception:
            pass
    payload = rank_concept_leaders(
        concept_name, start=start, end=end, top_n=top_n
    )
    if payload.get("leaders"):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload
