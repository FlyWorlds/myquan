"""通达信概念板块轮动数据（热力表 payload）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from .metrics import (
    METRIC_FIELD,
    ROTATION_METRICS,
    build_member_stats_map,
    enrich_concept_row,
    fetch_em_concept_main_flow,
)
from .rotation import (
    _merge_snaps,
    _session_label,
    _today,
)
from .tdx import fetch_tdx_board_members, fetch_tdx_concept_history, fetch_tdx_concept_spot


def _rank_day_multi(
    boards: list[dict[str, Any]],
    metric: str,
    top_n: int = 10,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    field = METRIC_FIELD[metric]
    rows = [b for b in boards if b.get(field) is not None]
    rows.sort(key=lambda x: float(x.get(field) or 0), reverse=True)

    def cell(b: dict[str, Any], rank: int) -> dict[str, Any]:
        return {
            "name": b.get("板块") or "",
            "value": b.get(field),
            "rank": rank,
            "label": b.get("label") or "",
            "metric": metric,
        }

    top = [cell(b, i + 1) for i, b in enumerate(rows[:top_n])]
    weak = rows[-top_n:] if len(rows) >= top_n else rows
    bottom = [cell(b, top_n - i) for i, b in enumerate(weak)]
    return top, bottom


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
    print("  聚合成分股涨停/涨跌比（新浪，首次较慢）…")
    member_stats = build_member_stats_map()
    main_flow = fetch_em_concept_main_flow()
    today_rows = []
    for _, r in boards_df.iterrows():
        base = {
            "板块": str(r.get("板块") or ""),
            "label": str(r.get("label") or ""),
            "涨跌幅": _clean(r.get("涨跌幅")),
            "涨停数": 0,
            "资金": _clean(r.get("资金")),
            "资金口径": str(r.get("资金口径") or "成交额"),
            "领涨名称": str(r.get("领涨名称") or ""),
            "领涨涨幅": _clean(r.get("领涨涨幅")),
        }
        today_rows.append(
            enrich_concept_row(
                base["板块"],
                base,
                member_stats=member_stats,
                main_flow=main_flow,
            )
        )
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
    for metric in ROTATION_METRICS:
        tops, bottoms = [], []
        for s in snaps_desc:
            t, b = _rank_day_multi(s.get("boards") or [], metric, top_n=top_n)
            tops.append(t)
            bottoms.append(b)
        by_metric[metric] = {"top": tops, "bottom": bottoms}

    members: dict[str, list[dict[str, Any]]] = {}
    if with_members:
        names: set[str] = set()
        for metric in ROTATION_METRICS:
            t, b = _rank_day_multi(today_rows, metric, top_n=top_n)
            for cell in t + b:
                if cell.get("name"):
                    names.add(str(cell["name"]))
        for s in snaps_desc[: min(3, len(snaps_desc))]:
            t, b = _rank_day_multi(s.get("boards") or [], "涨幅", top_n=top_n)
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
        "metrics": list(ROTATION_METRICS),
        "source": "通达信概念",
        "kinds": {
            "概念": {
                "dates": dates,
                "by_metric": by_metric,
                "members": members,
                "fund_note": (
                    "概念=通达信；成交额/涨幅=指数；涨停数/涨跌比=成分股聚合；"
                    "主力净额=东财概念（名称近似匹配）；强度=合成指标。"
                ),
                "board_count": int(len(boards_df)),
            }
        },
    }
