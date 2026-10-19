"""板块热门轮动数据生成（同花顺优先 → 东财 → 新浪 → 通达信）。

性能优化：
- 概念历史与今日榜、行业历史与今日榜、主力净流入三路并发拉取，消除串行等待与二次拉取
- 不在轮动接口主路径阻塞拉取 4000 只个股行情，优先复用后台实时线程已聚合的成分统计
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

import pandas as pd

from .metrics import (
    METRIC_FIELD,
    ROTATION_METRICS,
    enrich_concept_row,
    fetch_em_concept_main_flow,
)
from .rotation import (
    _filter_pure_concepts,
    _merge_snaps,
    _session_label,
    _today,
    fetch_em_board_spot,
)
from .tdx import fetch_tdx_board_members, fetch_tdx_concept_history, fetch_tdx_concept_spot
from .ths import (
    fetch_ths_board_members,
    fetch_ths_concept_history_and_spot,
    fetch_ths_industry_history_and_spot,
)


def _rank_day_multi(
    boards: list[dict[str, Any]],
    metric: str,
    top_n: int = 10,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    field = METRIC_FIELD.get(metric, "涨跌幅")
    rows = [b for b in boards if b.get(field) is not None]
    rows.sort(key=lambda x: float(x.get(field) or 0), reverse=True)

    def cell(b: dict[str, Any], rank: int) -> dict[str, Any]:
        return {
            "name": b.get("板块") or "",
            "value": b.get(field),
            "rank": rank,
            "label": b.get("label") or "",
            "metric": metric,
            "net_inflow": b.get("主力净额"),
            "amount": b.get("资金"),
            "leader_name": b.get("领涨名称") or "",
            "leader_chg": b.get("领涨涨幅"),
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


def compute_hot_periods_and_board_stats(
    snaps_desc: list[dict[str, Any]],
    today_rows: list[dict[str, Any]],
    *,
    top_n: int = 10,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    """计算 1/3/5/10 日热门板块排行与近 15 个交易日上榜统计。"""
    today_by_name: dict[str, dict[str, Any]] = {}
    for b in today_rows:
        n = str(b.get("板块") or "").strip()
        if n:
            today_by_name[n] = b

    hot_periods: dict[str, list[dict[str, Any]]] = {}
    for period in (1, 3, 5, 10):
        window = snaps_desc[: min(period, len(snaps_desc))]
        if not window:
            hot_periods[str(period)] = []
            continue
        acc: dict[str, dict[str, Any]] = {}
        for snap in reversed(window):
            for b in snap.get("boards") or []:
                name = str(b.get("板块") or "").strip()
                chg = _clean(b.get("涨跌幅"))
                if not name or chg is None:
                    continue
                item = acc.setdefault(
                    name,
                    {
                        "mult": 1.0,
                        "days": 0,
                        "net_inflow": 0.0,
                        "has_inflow": False,
                        "amount": 0.0,
                    },
                )
                item["mult"] *= 1.0 + chg / 100.0
                item["days"] += 1
                inflow = _clean(b.get("主力净额"))
                if inflow is not None:
                    item["net_inflow"] += inflow
                    item["has_inflow"] = True
                amt = _clean(b.get("资金"))
                if amt is not None:
                    item["amount"] += amt

        ranked: list[dict[str, Any]] = []
        for name, st in acc.items():
            t_row = today_by_name.get(name) or {}
            cum_chg = (
                (st["mult"] - 1.0) * 100.0
                if period > 1
                else (_clean(t_row.get("涨跌幅")) or (st["mult"] - 1.0) * 100.0)
            )
            inflow_val = (
                st["net_inflow"]
                if st["has_inflow"]
                else _clean(t_row.get("主力净额"))
            )
            amt_val = st["amount"] if st["amount"] > 0 else _clean(t_row.get("资金"))
            ranked.append(
                {
                    "name": name,
                    "code": str(t_row.get("label") or ""),
                    "chg_pct": round(cum_chg, 2),
                    "net_inflow": inflow_val,
                    "amount": amt_val,
                    "leader_name": str(t_row.get("领涨名称") or ""),
                    "leader_chg_pct": _clean(t_row.get("领涨涨幅")),
                    "period": period,
                }
            )
        ranked.sort(key=lambda x: float(x.get("chg_pct") or -999), reverse=True)
        for idx, r in enumerate(ranked[: max(top_n, 6)], start=1):
            r["rank"] = idx
        hot_periods[str(period)] = ranked[: max(top_n, 6)]

    appear_15d: dict[str, int] = {}
    for snap in snaps_desc[:15]:
        top_cells, _ = _rank_day_multi(snap.get("boards") or [], "涨幅", top_n=top_n)
        for cell in top_cells:
            n = str(cell.get("name") or "").strip()
            if n:
                appear_15d[n] = appear_15d.get(n, 0) + 1

    today_sorted = sorted(
        [b for b in today_rows if _clean(b.get("涨跌幅")) is not None],
        key=lambda x: float(x.get("涨跌幅") or -999),
        reverse=True,
    )
    board_stats: dict[str, dict[str, Any]] = {}
    for idx, b in enumerate(today_sorted, start=1):
        n = str(b.get("板块") or "").strip()
        if not n:
            continue
        board_stats[n] = {
            "name": n,
            "code": str(b.get("label") or ""),
            "today_rank": idx,
            "chg_pct": _clean(b.get("涨跌幅")),
            "net_inflow": _clean(b.get("主力净额")),
            "amount": _clean(b.get("资金")),
            "appear_15d": appear_15d.get(n, 1 if idx <= top_n else 0),
            "leader_name": str(b.get("领涨名称") or ""),
            "leader_chg_pct": _clean(b.get("领涨涨幅")),
        }
    for n, cnt in appear_15d.items():
        if n not in board_stats:
            board_stats[n] = {
                "name": n,
                "code": "",
                "today_rank": None,
                "chg_pct": None,
                "net_inflow": None,
                "amount": None,
                "appear_15d": cnt,
                "leader_name": "",
                "leader_chg_pct": None,
            }

    return hot_periods, board_stats


def _assemble_kind_block(
    *,
    kind: str,
    today_rows: list[dict[str, Any]],
    hist: list[dict[str, Any]],
    session: str,
    days: int,
    top_n: int,
    source: str,
    fund_note: str,
    members: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    today_snap = {
        "date": session,
        "kind": kind,
        "boards": today_rows,
        "source": source,
    }
    snaps = _merge_snaps(hist, today_snap, days=days)
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

    hot_periods, board_stats = compute_hot_periods_and_board_stats(
        snaps_desc, today_rows, top_n=top_n
    )

    if not members:
        try:
            from .concept_leaders import _stock_name_map
            from .tdx import lookup_member_codes

            name_map = _stock_name_map()
            ranked_names: set[str] = set()
            for col_group in by_metric.values():
                for col in (col_group.get("top") or [])[:5]:
                    for cell in col or []:
                        if cell.get("name"):
                            ranked_names.add(str(cell["name"]))
            for cards in hot_periods.values():
                for card in cards or []:
                    if card.get("name"):
                        ranked_names.add(str(card["name"]))
            prepacked: dict[str, list[dict[str, Any]]] = {}
            for bname in ranked_names:
                codes = lookup_member_codes(kind, bname) or lookup_member_codes(
                    "行业" if kind == "概念" else "概念", bname
                )
                if codes:
                    prepacked[bname] = [
                        {
                            "代码": c,
                            "名称": name_map.get(c, c),
                            "现价": None,
                            "涨跌幅": None,
                            "成交额": None,
                            "换手率": None,
                        }
                        for c in codes[:60]
                    ]
            members = prepacked
        except Exception:
            members = {}

    return {
        "dates": dates,
        "by_metric": by_metric,
        "hot_periods": hot_periods,
        "board_stats": board_stats,
        "members": members or {},
        "fund_note": fund_note,
        "board_count": int(len(today_rows)),
    }


def _enrich_df_rows(
    boards_df: pd.DataFrame,
    *,
    member_stats: dict[str, dict[str, Any]],
    main_flow: dict[str, float],
) -> list[dict[str, Any]]:
    today_rows: list[dict[str, Any]] = []
    if boards_df is None or boards_df.empty:
        return today_rows
    for _, r in boards_df.iterrows():
        name = str(r.get("板块") or "").strip()
        if not name:
            continue
        fund = _clean(r.get("资金"))
        inflow = _clean(r.get("主力净额"))
        if inflow is not None:
            main_flow.setdefault(name, inflow)
        elif fund is not None and str(r.get("资金口径") or "") == "主力净流入":
            main_flow.setdefault(name, fund)
        base = {
            "板块": name,
            "label": str(r.get("label") or ""),
            "涨跌幅": _clean(r.get("涨跌幅")),
            "涨停数": int(r.get("涨停数") or 0),
            "资金": _clean(r.get("总成交额")) or fund,
            "资金口径": str(r.get("资金口径") or "成交额"),
            "领涨名称": str(r.get("领涨名称") or ""),
            "领涨涨幅": _clean(r.get("领涨涨幅")),
        }
        enriched = enrich_concept_row(
            name,
            base,
            member_stats=member_stats,
            main_flow=main_flow,
        )
        today_rows.append(enriched)
    return today_rows


def _fetch_all_main_flows() -> dict[str, float]:
    main_flow = fetch_em_concept_main_flow()
    try:
        ind_em = fetch_em_board_spot("行业")
        if ind_em is not None and not ind_em.empty:
            for _, r in ind_em.iterrows():
                n = str(r.get("板块") or "").strip()
                fl = _clean(r.get("主力净额")) or (
                    _clean(r.get("资金"))
                    if str(r.get("资金口径") or "") == "主力净流入"
                    else None
                )
                if n and fl is not None:
                    main_flow.setdefault(n, fl)
    except Exception:
        pass
    return main_flow


def build_ths_rotation_payload(
    *,
    days: int = 20,
    top_n: int = 10,
    with_members: bool = False,
) -> dict[str, Any]:
    """同花顺热点轮动完整数据（概念历史+行业历史+主力净流入三路并发拉取）。"""
    session = _today()
    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_concept = pool.submit(fetch_ths_concept_history_and_spot, days)
        fut_ind = pool.submit(fetch_ths_industry_history_and_spot, days)
        fut_flow = pool.submit(_fetch_all_main_flows)

        try:
            concept_hist, concept_df = fut_concept.result()
        except Exception:
            concept_hist, concept_df = [], pd.DataFrame()
        try:
            ind_hist, ind_df = fut_ind.result()
        except Exception:
            ind_hist, ind_df = [], pd.DataFrame()
        try:
            main_flow = fut_flow.result()
        except Exception:
            main_flow = {}

    member_stats: dict[str, dict[str, Any]] = {}
    concept_today = _enrich_df_rows(
        concept_df, member_stats=member_stats, main_flow=main_flow
    )
    if not concept_today:
        raise RuntimeError("同花顺概念行情为空")

    ind_today = _enrich_df_rows(
        ind_df, member_stats=member_stats, main_flow=main_flow
    )

    concept_block = _assemble_kind_block(
        kind="概念",
        today_rows=concept_today,
        hist=concept_hist,
        session=session,
        days=days,
        top_n=top_n,
        source="同花顺概念",
        fund_note="数据源：同花顺概念指数（d.10jqka.com.cn）+ 主力净买/净卖（数据库持久化）。",
    )
    kinds: dict[str, Any] = {"概念": concept_block}
    if ind_today:
        kinds["行业"] = _assemble_kind_block(
            kind="行业",
            today_rows=ind_today,
            hist=ind_hist,
            session=session,
            days=days,
            top_n=top_n,
            source="同花顺行业",
            fund_note="数据源：同花顺行业指数 + 净流入（数据库持久化）。",
        )

    return {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "session": session,
        "top_n": top_n,
        "days": days,
        "metrics": list(ROTATION_METRICS),
        "source": "同花顺热点轮动",
        "kinds": kinds,
    }


def build_em_concept_rotation_payload(
    *,
    days: int = 20,
    top_n: int = 10,
) -> dict[str, Any]:
    """东财板块轮动（同花顺不可用时的快速回退，支持概念+行业）。"""
    session = _today()
    boards_df = _filter_pure_concepts(fetch_em_board_spot("概念"))
    if boards_df is None or boards_df.empty:
        raise RuntimeError("东财概念行情为空")
    member_stats: dict[str, dict[str, Any]] = {}
    main_flow: dict[str, float] = {}
    today_rows = _enrich_df_rows(
        boards_df, member_stats=member_stats, main_flow=main_flow
    )
    kinds: dict[str, Any] = {
        "概念": _assemble_kind_block(
            kind="概念",
            today_rows=today_rows,
            hist=[],
            session=session,
            days=days,
            top_n=top_n,
            source="东财概念",
            fund_note="数据源：东方财富概念板块（涨幅/成交额/主力净流入）。",
        )
    }
    try:
        ind_df = fetch_em_board_spot("行业")
        ind_rows = _enrich_df_rows(
            ind_df, member_stats=member_stats, main_flow=main_flow
        )
        if ind_rows:
            kinds["行业"] = _assemble_kind_block(
                kind="行业",
                today_rows=ind_rows,
                hist=[],
                session=session,
                days=days,
                top_n=top_n,
                source="东财行业",
                fund_note="数据源：东方财富行业板块（涨幅/成交额/主力净流入）。",
            )
    except Exception:
        pass

    return {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "session": session,
        "top_n": top_n,
        "days": days,
        "metrics": list(ROTATION_METRICS),
        "source": "东财板块轮动",
        "kinds": kinds,
    }


def build_sina_rotation_payload(
    *,
    days: int = 20,
    top_n: int = 10,
) -> dict[str, Any]:
    """新浪板块轮动快速回退（单请求 ~0.3s，支持概念+行业）。"""
    from .sina_boards import fetch_sina_boards

    session = _today()
    kinds: dict[str, Any] = {}
    for kind_zh, kind_en in (("概念", "concept"), ("行业", "industry")):
        try:
            boards = fetch_sina_boards(kind_en, timeout=3.0)
        except Exception:
            boards = []
        rows: list[dict[str, Any]] = []
        for b in boards:
            base = {
                "板块": b.name,
                "label": b.code,
                "涨跌幅": b.chg_pct,
                "涨停数": 0,
                "资金": b.amount,
                "资金口径": "成交额",
                "领涨名称": b.leader_name,
                "领涨涨幅": b.leader_chg_pct,
            }
            rows.append(enrich_concept_row(b.name, base))
        if rows:
            kinds[kind_zh] = _assemble_kind_block(
                kind=kind_zh,
                today_rows=rows,
                hist=[],
                session=session,
                days=days,
                top_n=top_n,
                source=f"新浪{kind_zh}",
                fund_note=f"数据源：新浪财经{kind_zh}板块实时行情。",
            )
    if not kinds.get("概念"):
        raise RuntimeError("新浪板块行情为空")
    return {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "session": session,
        "top_n": top_n,
        "days": days,
        "metrics": list(ROTATION_METRICS),
        "source": "新浪板块轮动",
        "kinds": kinds,
    }


def build_tdx_concept_rotation_payload(
    *,
    days: int = 20,
    top_n: int = 10,
    with_members: bool = True,
) -> dict[str, Any]:
    """通达信概念轮动前端数据（近 N 日热力表）。"""
    session = _today()
    concept_hist = fetch_tdx_concept_history(days=days)
    boards_df = fetch_tdx_concept_spot()
    main_flow = fetch_em_concept_main_flow()
    today_rows = _enrich_df_rows(
        boards_df, member_stats={}, main_flow=main_flow
    )
    concept_block = _assemble_kind_block(
        kind="概念",
        today_rows=today_rows,
        hist=concept_hist,
        session=session,
        days=days,
        top_n=top_n,
        source="通达信概念",
        fund_note="概念=通达信；成交额/涨幅=指数；主力净额=东财概念。",
    )
    return {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "session": session,
        "top_n": top_n,
        "days": days,
        "metrics": list(ROTATION_METRICS),
        "source": "通达信概念",
        "kinds": {"概念": concept_block},
    }
