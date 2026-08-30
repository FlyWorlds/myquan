"""通达信概念盘中实时行情（单连接批量拉取，供盯盘 5s 推送）。"""

from __future__ import annotations

import threading
from typing import Any

from .tdx import _clean, _connect_api, _stock_market, load_concepts, load_members_index, resolve_concept_by_name

_lock = threading.Lock()
_concept_boards: list[dict[str, str]] | None = None


def _boards() -> list[dict[str, str]]:
    global _concept_boards
    if _concept_boards is None:
        _concept_boards = load_concepts()
    return _concept_boards


def fetch_concept_index_spot_live() -> dict[str, dict[str, Any]]:
    """全部通达信概念指数现价（name -> 涨跌幅/资金/code）。"""
    boards = _boards()
    if not boards:
        return {}

    code_name = {b["code"]: b["name"] for b in boards}
    pairs = [(1, str(b["code"])) for b in boards]
    raw: dict[str, dict[str, Any]] = {}

    api = _connect_api()
    try:
        step = 80
        for i in range(0, len(pairs), step):
            batch = pairs[i : i + step]
            quotes = api.get_security_quotes(batch) or []
            for q in quotes:
                code = str(q.get("code") or "").strip()
                if not code:
                    continue
                price = _clean(q.get("price"))
                prev = _clean(q.get("last_close"))
                chg = ((price / prev - 1.0) * 100.0) if price and prev else None
                raw[code] = {
                    "code": code,
                    "name": code_name.get(code, code),
                    "涨跌幅": chg,
                    "close": price,
                    "资金": _clean(q.get("amount")),
                    "资金口径": "成交额",
                }
    finally:
        api.disconnect()

    by_name: dict[str, dict[str, Any]] = {}
    for b in boards:
        row = raw.get(b["code"])
        if row:
            by_name[b["name"]] = row
    return by_name


def member_codes_for_concept(name: str, *, limit: int = 200) -> list[str]:
    index = load_members_index()
    codes = (index.get("概念") or {}).get(str(name).strip()) or []
    return [str(c).zfill(6) for c in codes[:limit]]


def leader_codes_from_detail(detail: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()
    for seg in detail.get("segments") or []:
        for leader in seg.get("leaders") or []:
            c = str(leader.get("code") or "").zfill(6)
            if c and c not in seen:
                seen.add(c)
                codes.append(c)
    for m in detail.get("members_preview") or []:
        c = str(m.get("code") or "").zfill(6)
        if c and c not in seen:
            seen.add(c)
            codes.append(c)
    return codes


def stock_quotes_by_codes(codes: list[str]) -> dict[str, dict[str, Any]]:
    """成分股/龙头现价（pytdx 批量）。"""
    if not codes:
        return {}
    pairs = [(_stock_market(c), str(c).zfill(6)) for c in codes]
    out: dict[str, dict[str, Any]] = {}

    api = _connect_api()
    try:
        step = 40
        for i in range(0, len(pairs), step):
            quotes = api.get_security_quotes(pairs[i : i + step]) or []
            for q in quotes:
                code = str(q.get("code") or "").zfill(6)
                price = _clean(q.get("price"))
                prev = _clean(q.get("last_close"))
                chg = ((price / prev - 1.0) * 100.0) if price and prev else None
                out[code] = {
                    "code": code,
                    "price": price,
                    "chgPct": chg,
                    "amount": _clean(q.get("amount")),
                }
    finally:
        api.disconnect()
    return out


def concept_index_quote(name: str, today_map: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    row = today_map.get(name)
    if not row:
        meta = resolve_concept_by_name(name)
        if not meta:
            return None
        row = today_map.get(meta.get("name") or name)
    if not row:
        return None
    return {
        "name": name,
        "code": row.get("code"),
        "price": row.get("close"),
        "chgPct": row.get("涨跌幅"),
        "amount": row.get("资金"),
    }
