"""概念龙头股评分 API（编排层，打分真源见 strategy/factor16_leader_score.py）。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from backtest.ai_concept_f1_f13_report import OOS_START, THR, _today_ymd, _to_symbol, fetch_one
from strategy.factor16_leader_score import (
    DEFAULT_PARAMS,
    eval_stock_metrics_from_daily,
    factor16_signal,
    format_leader_row,
)

from .concept_leaders import _stock_name_map
from .live import member_codes_for_concept

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"

DEFAULT_START = "2025-01-01"
TOP_N = int(DEFAULT_PARAMS["top_k"])
MAX_CANDIDATES = 60
FETCH_WORKERS = 8


def _iso_to_ymd(s: str) -> str:
    return str(s).replace("-", "")[:8]


def _ymd_to_iso(s: str) -> str:
    t = str(s).replace("-", "")[:8]
    return f"{t[:4]}-{t[4:6]}-{t[6:8]}"


def rank_concept_leaders(
    concept_name: str,
    *,
    start: str = DEFAULT_START,
    end: str | None = None,
    top_n: int = TOP_N,
    max_candidates: int = MAX_CANDIDATES,
) -> dict[str, Any]:
    """概念成分股：因子16 打分并取 TopN。"""
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

    daily_map: dict[str, Any] = {}
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
                    eval_stock_metrics_from_daily,
                    c,
                    daily_map[sym],
                    name=names.get(c, c),
                    oos_start=oos_start,
                    oos_end=oos_end,
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

    import pandas as pd

    metrics = pd.DataFrame(rows)
    sig = factor16_signal(metrics=metrics, top_k=top_n, params={"mainboard_only": False})
    picks = sig["picks"]
    leaders = [
        format_leader_row(r, rank=int(r["rank"]))
        for _, r in picks.iterrows()
    ]

    return {
        "concept": concept_name,
        "start": _ymd_to_iso(oos_start),
        "end": _ymd_to_iso(oos_end),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "factor_id": "factor16",
        "scoring": sig.get("scoring")
        or {
            "source": "strategy/factor16_leader_score.py",
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
