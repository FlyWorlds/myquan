"""通达信概念板块轮动数据（热力表 payload）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from .rotation import (
    METRICS,
    METRIC_FIELD,
    _collect_ranked_names,
    _merge_snaps,
    _rank_day,
    _session_label,
    _today,
)
from .tdx import fetch_tdx_board_members, fetch_tdx_concept_history, fetch_tdx_concept_spot


def _clean(v: Any) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        x = float(v)
        return None if pd.isna(x) else x
    except (TypeError, ValueError):
        return None


def _boards_df_to_rows(boards_df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, r in boards_df.iterrows():
        rows.append(
            {
                "板块": str(r.get("板块") or ""),
                "label": str(r.get("label") or ""),
                "涨跌幅": _clean(r.get("涨跌幅")),
                "涨停数": int(r.get("涨停数") or 0),
                "资金": _clean(r.get("资金")),
                "资金口径": str(r.get("资金口径") or "成交额"),
                "领涨名称": str(r.get("领涨名称") or ""),
                "领涨涨幅": _clean(r.get("领涨涨幅")),
            }
        )
    return rows


def _fetch_tdx_members(names: set[str]) -> dict[str, list[dict[str, Any]]]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    members: dict[str, list[dict[str, Any]]] = {}
    if not names:
        return members

    def _one(name: str) -> tuple[str, list[dict[str, Any]]]:
        try:
            df = fetch_tdx_board_members("概念", name, with_quotes=True, limit=50)
        except Exception:
            return name, []
        rows: list[dict[str, Any]] = []
        code_col = "纯代码" if "纯代码" in df.columns else "代码"
        for _, m in df.iterrows():
            code = str(m.get(code_col) or "").zfill(6)
            rows.append(
                {
                    "代码": code,
                    "名称": str(m.get("名称") or code),
                    "现价": _clean(m.get("现价")),
                    "涨跌幅": _clean(m.get("涨跌幅")),
                    "换手率": _clean(m.get("换手率")),
                    "成交额": _clean(m.get("成交额")),
                }
            )
        return name, rows

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_one, n) for n in sorted(names)]
        for fut in as_completed(futs):
            name, rows = fut.result()
            members[name] = rows
    return members


def build_tdx_concept_rotation_payload(
    *,
    days: int = 20,
    top_n: int = 10,
    with_members: bool = True,
) -> dict[str, Any]:
    """生成通达信概念轮动前端数据（近 N 日热力表）。"""
    session = _today()
    print(f"  通达信概念历史近 {days} 日…")
    concept_hist = fetch_tdx_concept_history(days=days)
    print("  通达信概念今日行情…")
    boards_df = fetch_tdx_concept_spot()
    today_rows = _boards_df_to_rows(boards_df)
    today_snap = {
        "date": session,
        "kind": "概念",
        "boards": today_rows,
        "source": "通达信概念",
    }
    snaps = _merge_snaps(concept_hist, today_snap, days=days)
    snaps_desc = list(reversed(snaps))
    dates = [_session_label(str(s.get("date") or "")) for s in snaps_desc]

    by_metric: dict[str, Any] = {}
    for metric in METRICS:
        tops, bottoms = [], []
        for s in snaps_desc:
            t, b = _rank_day(s.get("boards") or [], metric, top_n=top_n)
            tops.append(t)
            bottoms.append(b)
        by_metric[metric] = {"top": tops, "bottom": bottoms}

    members: dict[str, list[dict[str, Any]]] = {}
    if with_members:
        names = _collect_ranked_names(today_rows, top_n)
        for s in snaps_desc[: min(3, len(snaps_desc))]:
            t, b = _rank_day(s.get("boards") or [], "涨幅", top_n=top_n)
            for cell in t + b:
                if cell.get("name"):
                    names.add(str(cell["name"]))
        print(f"  拉取通达信概念成分 {len(names)} 个…")
        members = _fetch_tdx_members(names)

    return {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "session": session,
        "top_n": top_n,
        "days": days,
        "metrics": list(METRICS),
        "source": "通达信概念",
        "kinds": {
            "概念": {
                "dates": dates,
                "by_metric": by_metric,
                "members": members,
                "fund_note": "概念=通达信纯概念（tdxzs 类别4）；资金=板块成交额。",
                "board_count": int(len(boards_df)),
            }
        },
    }
