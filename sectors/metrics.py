"""板块轮动指标：涨幅/涨停数/涨跌比/成交额/主力净额/强度。"""

from __future__ import annotations

import threading
from typing import Any

# Web 筛选与排名口径（与通达信 App 菜单对齐）
ROTATION_METRICS: tuple[str, ...] = (
    "涨幅",
    "涨停数",
    "涨跌比",
    "成交额",
    "主力净额",
    "强度",
)

METRIC_FIELD: dict[str, str] = {
    "涨幅": "涨跌幅",
    "涨停数": "涨停数",
    "涨跌比": "涨跌比",
    "成交额": "资金",
    "主力净额": "主力净额",
    "强度": "强度",
}


def code_to_sina(code: str) -> str:
    c = str(code).zfill(6)
    if c.startswith(("6", "5", "9")):
        return f"sh{c}"
    return f"sz{c}"


def _is_limit_up(chg: float | None, code: str) -> bool:
    if chg is None:
        return False
    c = str(code).zfill(6)
    thr = 19.5 if c.startswith(("30", "68", "92", "43", "83", "87")) else 9.5
    return chg >= thr


def stats_from_member_quotes(
    codes: list[str],
    quotes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """由成分股现价聚合涨停数、涨跌比等。"""
    up = down = flat = limit_up = 0
    for code in codes:
        c = str(code).zfill(6)
        chg = quotes.get(c, {}).get("chgPct")
        if chg is None:
            flat += 1
            continue
        if _is_limit_up(chg, c):
            limit_up += 1
        if chg > 0:
            up += 1
        elif chg < 0:
            down += 1
        else:
            flat += 1
    ratio = (up / down) if down > 0 else float(up)
    return {
        "涨停数": limit_up,
        "上涨家数": up,
        "下跌家数": down,
        "平盘家数": flat,
        "涨跌比": round(ratio, 2),
    }


def compute_strength(
    *,
    chg_pct: float | None,
    up_down_ratio: float | None,
    limit_up: int = 0,
) -> float | None:
    """合成强度（研究口径，非通达信官方公式）。"""
    if chg_pct is None:
        return None
    ratio = up_down_ratio if up_down_ratio is not None else 1.0
    ratio = min(max(ratio, 0.0), 10.0)
    return round(chg_pct * (1.0 + ratio / 5.0) + limit_up * 0.35, 2)


def fetch_em_concept_main_flow() -> dict[str, float]:
    """东财概念板块主力净流入（名称可能与通达信略有差异，能匹配则填入）。"""
    try:
        from .rotation import fetch_em_board_spot

        df = fetch_em_board_spot("概念")
    except Exception:
        return {}
    if df is None or df.empty:
        return {}
    out: dict[str, float] = {}
    for _, r in df.iterrows():
        name = str(r.get("板块") or "").strip()
        flow = r.get("资金")
        if name and flow is not None and str(r.get("资金口径") or "") == "主力净流入":
            try:
                out[name] = float(flow)
            except (TypeError, ValueError):
                continue
    return out


_members_index_cache: dict[str, list[str]] | None = None
_members_lock = threading.Lock()


def concept_members_index() -> dict[str, list[str]]:
    global _members_index_cache
    with _members_lock:
        if _members_index_cache is not None:
            return _members_index_cache
        from .tdx import load_members_index

        raw = load_members_index().get("概念") or {}
        _members_index_cache = {
            str(k): [str(c).zfill(6) for c in v] for k, v in raw.items()
        }
        return _members_index_cache


def all_member_codes() -> list[str]:
    seen: set[str] = set()
    for codes in concept_members_index().values():
        seen.update(codes)
    return sorted(seen)


def fetch_member_quotes_sina(codes: list[str]) -> dict[str, dict[str, Any]]:
    """新浪批量现价 → {code: {chgPct, price}}。"""
    import sys
    from pathlib import Path

    hs = Path(__file__).resolve().parents[1] / "holdingStocks"
    if str(hs) not in sys.path:
        sys.path.insert(0, str(hs))
    from quote_feed import fetch_sina_batch

    sinas = [code_to_sina(c) for c in codes]
    batch = fetch_sina_batch(sinas)
    out: dict[str, dict[str, Any]] = {}
    for code in codes:
        sina = code_to_sina(code).lower()
        spot = batch.get(sina)
        if not spot:
            continue
        c = str(code).zfill(6)
        last = spot.get("last")
        prev = spot.get("prev_close")
        chg = spot.get("day_chg_pct")
        if chg is None and last and prev:
            try:
                chg = (float(last) / float(prev) - 1.0) * 100.0
            except (TypeError, ValueError, ZeroDivisionError):
                chg = None
        out[c] = {
            "code": c,
            "price": last,
            "chgPct": chg,
            "amount": spot.get("amount"),
        }
    return out


def build_member_stats_map(
    quotes: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """全部通达信概念的成分股聚合指标。"""
    index = concept_members_index()
    if quotes is None:
        quotes = fetch_member_quotes_sina(all_member_codes())
    out: dict[str, dict[str, Any]] = {}
    for name, codes in index.items():
        out[name] = stats_from_member_quotes(codes, quotes)
    return out


def _lookup_member_stats(
    name: str, member_stats: dict[str, dict[str, Any]] | None
) -> dict[str, Any]:
    if not member_stats:
        return {}
    hit = member_stats.get(name)
    if hit:
        return hit
    stripped = str(name).replace("概念", "").strip()
    if stripped and stripped != name:
        for key in (stripped, stripped + "概念"):
            if key in member_stats:
                return member_stats[key]
    return {}


def enrich_concept_row(
    name: str,
    base: dict[str, Any],
    *,
    member_stats: dict[str, dict[str, Any]] | None = None,
    main_flow: dict[str, float] | None = None,
) -> dict[str, Any]:
    """合并指数行情 + 成分聚合 + 主力净额 + 强度。"""
    row = dict(base)
    ms = _lookup_member_stats(name, member_stats)
    row["涨停数"] = int(ms.get("涨停数") or 0)
    row["涨跌比"] = ms.get("涨跌比")
    row["上涨家数"] = ms.get("上涨家数")
    row["下跌家数"] = ms.get("下跌家数")
    if main_flow and name in main_flow:
        row["主力净额"] = main_flow[name]
        row["主力净额口径"] = "东财概念主力净流入"
    else:
        row["主力净额"] = None
    row["强度"] = compute_strength(
        chg_pct=row.get("涨跌幅"),
        up_down_ratio=row.get("涨跌比"),
        limit_up=int(row.get("涨停数") or 0),
    )
    if row.get("资金") is not None:
        row["资金口径"] = row.get("资金口径") or "成交额"
    return row
