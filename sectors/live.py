"""概念盘中实时行情（通达信优先，连不上则东财回退）。"""

from __future__ import annotations

from typing import Any

from .tdx import _clean, _connect_api, _stock_market, load_concepts, load_members_index, resolve_concept_by_name, tdx_hq_available

_concept_boards: list[dict[str, str]] | None = None
_live_source = "通达信概念"


def live_source() -> str:
    return _live_source


def _boards() -> list[dict[str, str]]:
    global _concept_boards
    if _concept_boards is None:
        _concept_boards = load_concepts()
    return _concept_boards


def _spot_from_tdx() -> dict[str, dict[str, Any]]:
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


def _spot_from_em() -> dict[str, dict[str, Any]]:
    from .rotation import _filter_pure_concepts, fetch_em_board_spot

    df = _filter_pure_concepts(fetch_em_board_spot("概念"))
    if df is None or df.empty:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for _, r in df.iterrows():
        name = str(r.get("板块") or "").strip()
        if not name:
            continue
        out[name] = {
            "code": str(r.get("label") or ""),
            "name": name,
            "涨跌幅": _clean(r.get("涨跌幅")),
            "close": _clean(r.get("现价")),
            "资金": _clean(r.get("资金")),
            "资金口径": str(r.get("资金口径") or "成交额"),
        }
    return out


def fetch_concept_index_spot_live() -> dict[str, dict[str, Any]]:
    """概念指数现价（name -> 涨跌幅/资金/code）。通达信失败则东财。"""
    global _live_source
    if tdx_hq_available():
        try:
            spot = _spot_from_tdx()
            if spot:
                _live_source = "通达信概念"
                return spot
        except Exception:
            pass
    spot = _spot_from_em()
    if not spot:
        raise RuntimeError("概念行情不可用：通达信连不上，东财也无数据")
    _live_source = "东财概念"
    return spot


def member_codes_for_concept(name: str, *, limit: int = 200) -> list[str]:
    index = load_members_index()
    codes = (index.get("概念") or {}).get(str(name).strip()) or []
    out = [str(c).zfill(6) for c in codes[:limit] if str(c).strip()]
    if out:
        return out
    try:
        from .rotation import em_concept_code_of, fetch_em_concept_members

        bk = em_concept_code_of(name)
        if not bk:
            return []
        rows = fetch_em_concept_members(bk, limit=limit)
        return [
            str(m.get("纯代码") or m.get("代码") or "").zfill(6)
            for m in rows
            if str(m.get("纯代码") or m.get("代码") or "").strip()
        ][:limit]
    except Exception:
        return []


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


def _quotes_from_tdx(codes: list[str]) -> dict[str, dict[str, Any]]:
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


def stock_quotes_by_codes(codes: list[str]) -> dict[str, dict[str, Any]]:
    """成分股/龙头现价：通达信批量，失败则新浪。"""
    if not codes:
        return {}
    if tdx_hq_available():
        try:
            return _quotes_from_tdx(codes)
        except Exception:
            pass
    from .metrics import fetch_member_quotes_sina

    raw = fetch_member_quotes_sina([str(c).zfill(6) for c in codes])
    return {
        c: {
            "code": c,
            "price": v.get("price"),
            "chgPct": v.get("chgPct"),
            "amount": None,
        }
        for c, v in raw.items()
    }


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
