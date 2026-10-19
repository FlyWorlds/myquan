"""板块盘中实时行情与成分股下钻（极速版：内存索引+东财/同花顺并发竞速+60s结果缓存）。

性能优化：
- `fetch_concept_member_rows`：
  1) 60s 进程内缓存命中直接 0ms 返回；
  2) 优先查内存 `sectors_members_index`（0ms）+ 新浪单次批量现价（~120ms），按涨跌幅排序立即返回；
  3) 若内存索引未收录（如同花顺特色新概念），并发竞速请求东财 JSON 接口（~150ms）与同花顺单页（1.8s 超时），谁先返回用谁，彻底消除串行等待 `q.10jqka.com.cn` 超时的 3-6s 卡顿。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .tdx import (
    _clean,
    _connect_api,
    _stock_market,
    load_concepts,
    resolve_concept_by_name,
    tdx_hq_available,
)
from .ths import (
    THS_CONCEPT_SKIP,
    candidate_concept_names,
    fetch_ths_board_members,
    fetch_ths_industry_spot,
    load_concept_clid_map,
    load_concept_code_map,
)

_LIVE_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="sector-live")
_concept_boards: list[dict[str, str]] | None = None
_live_source = "同花顺热点轮动"
_MEMBERS_ROW_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_MEMBERS_CODE_CACHE: dict[str, list[str]] = {}
_MEMBERS_CACHE_TTL = 120.0


def live_source() -> str:
    return _live_source


def _boards() -> list[dict[str, str]]:
    global _concept_boards
    if _concept_boards is None:
        _concept_boards = load_concepts()
    return _concept_boards


def reload_concept_boards() -> list[dict[str, str]]:
    global _concept_boards
    _concept_boards = load_concepts()
    return _concept_boards


def _spot_from_sina() -> dict[str, dict[str, Any]]:
    from .sina_boards import fetch_sina_boards

    out: dict[str, dict[str, Any]] = {}
    for kind_en in ("concept", "industry"):
        try:
            for row in fetch_sina_boards(kind_en, timeout=2.0):
                if not row.name or row.name in out:
                    continue
                out[row.name] = {
                    "code": row.code,
                    "name": row.name,
                    "涨跌幅": row.chg_pct,
                    "close": row.avg_price,
                    "资金": row.amount,
                    "主力净额": None,
                    "资金口径": "成交额",
                    "领涨名称": row.leader_name,
                    "领涨涨幅": row.leader_chg_pct,
                }
        except Exception:
            continue
    return out


def _spot_from_em() -> dict[str, dict[str, Any]]:
    from .rotation import _filter_pure_concepts, em_available, fetch_em_board_spot

    if not em_available():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for kind in ("概念", "行业"):
        try:
            raw_df = fetch_em_board_spot(kind)
            df = _filter_pure_concepts(raw_df) if kind == "概念" else raw_df
            if df is None or df.empty:
                continue
            for _, r in df.iterrows():
                name = str(r.get("板块") or "").strip()
                if not name or name in out:
                    continue
                out[name] = {
                    "code": str(r.get("label") or ""),
                    "name": name,
                    "涨跌幅": _clean(r.get("涨跌幅")),
                    "close": _clean(r.get("现价")),
                    "资金": _clean(r.get("总成交额")) or _clean(r.get("资金")),
                    "主力净额": _clean(r.get("主力净额")),
                    "资金口径": str(r.get("资金口径") or "成交额"),
                    "领涨名称": str(r.get("领涨名称") or ""),
                    "领涨涨幅": _clean(r.get("领涨涨幅")),
                }
        except Exception:
            continue
    return out


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


def fetch_concept_index_spot_live() -> dict[str, dict[str, Any]]:
    """板块指数实时现价（同花顺字典 + 新浪高速摘要/同花顺行业，耗时 ~0.2s，不卡东财）。"""
    global _live_source
    sina_spot = _spot_from_sina()
    em_spot = _spot_from_em()
    base_spot = {**sina_spot, **em_spot}
    clid_map = load_concept_clid_map()
    code_map = load_concept_code_map()

    out: dict[str, dict[str, Any]] = {}
    for ths_name, detail_code in code_map.items():
        if ths_name in THS_CONCEPT_SKIP:
            continue
        clid = clid_map.get(ths_name, detail_code)
        for cand in candidate_concept_names(ths_name):
            src_row = base_spot.get(cand)
            if src_row:
                row = dict(src_row)
                row["name"] = ths_name
                row["code"] = clid
                out[ths_name] = row
                break

    try:
        idf = fetch_ths_industry_spot()
        if idf is not None and not idf.empty:
            for _, r in idf.iterrows():
                name = str(r.get("板块") or "").strip()
                if not name or name in out:
                    continue
                out[name] = {
                    "code": str(r.get("label") or ""),
                    "name": name,
                    "涨跌幅": _clean(r.get("涨跌幅")),
                    "close": None,
                    "资金": _clean(r.get("总成交额")) or _clean(r.get("资金")),
                    "主力净额": _clean(r.get("主力净额")),
                    "资金口径": str(r.get("资金口径") or "主力净流入"),
                    "领涨名称": str(r.get("领涨名称") or ""),
                    "领涨涨幅": _clean(r.get("领涨涨幅")),
                }
    except Exception:
        pass

    for name, row in base_spot.items():
        out.setdefault(name, row)

    if out:
        _live_source = "同花顺热点轮动"
        return out

    if tdx_hq_available():
        try:
            tdx_spot = _spot_from_tdx()
            if tdx_spot:
                _live_source = "通达信概念"
                return tdx_spot
        except Exception:
            pass

    raise RuntimeError("板块实时行情不可用：同花顺、新浪、东财与通达信均无数据")


def member_codes_for_concept(name: str, *, limit: int = 200) -> list[str]:
    """按板块名快速获取成分股代码列表（优先内存缓存与本地索引 0ms，其次同花顺/东财）。"""
    name = str(name or "").strip()
    if not name:
        return []
    if name in _MEMBERS_CODE_CACHE and _MEMBERS_CODE_CACHE[name]:
        return _MEMBERS_CODE_CACHE[name][:limit]

    from .tdx import lookup_member_codes

    out = lookup_member_codes("概念", name) or lookup_member_codes("行业", name)
    if out:
        _MEMBERS_CODE_CACHE[name] = out
        return out[:limit]

    for kind in ("概念", "行业"):
        try:
            df = fetch_ths_board_members(kind, name, limit=limit)
            if df is not None and not df.empty:
                col = "纯代码" if "纯代码" in df.columns else "代码"
                out = [
                    str(c).zfill(6)
                    for c in df[col].tolist()
                    if str(c).strip().isdigit()
                ]
                if out:
                    _MEMBERS_CODE_CACHE[name] = out
                    return out[:limit]
        except Exception:
            continue

    try:
        from .rotation import em_available, em_concept_code_of, fetch_em_concept_members

        if em_available():
            bk = em_concept_code_of(name)
            if bk:
                rows = fetch_em_concept_members(bk, limit=limit)
                out = [
                    str(m.get("纯代码") or m.get("代码") or "").zfill(6)
                    for m in rows
                    if str(m.get("纯代码") or m.get("代码") or "").strip()
                ]
                if out:
                    _MEMBERS_CODE_CACHE[name] = out
                    return out[:limit]
    except Exception:
        pass

    return []


def _fetch_em_members_rows(
    name: str, limit: int, names: dict[str, str]
) -> dict[str, Any] | None:
    try:
        from .rotation import em_available, em_concept_code_of, fetch_em_concept_members
        from .stock_names import stock_name_of

        if not em_available():
            return None
        bk = em_concept_code_of(name)
        if not bk:
            return None
        raw = fetch_em_concept_members(bk, limit=limit)
        members = [
            {
                "代码": str(m.get("纯代码") or m.get("代码") or "").zfill(6),
                "名称": str(
                    m.get("名称")
                    or names.get(str(m.get("代码") or "").zfill(6))
                    or stock_name_of(m.get("代码"))
                ),
                "现价": m.get("现价"),
                "涨跌幅": m.get("涨跌幅"),
                "成交额": m.get("成交额"),
                "换手率": m.get("换手率"),
            }
            for m in raw
            if str(m.get("纯代码") or m.get("代码") or "").strip()
        ]
        if members:
            _MEMBERS_CODE_CACHE[name] = [m["代码"] for m in members]
            return {
                "name": name,
                "source": "东财板块",
                "code": bk,
                "members": members,
                "count": len(members),
            }
    except Exception:
        pass
    return None


def _fetch_ths_members_rows(
    name: str, kind: str, limit: int, names: dict[str, str]
) -> dict[str, Any] | None:
    from .stock_names import stock_name_of

    search_kinds = ["行业", "概念"] if kind == "行业" else ["概念", "行业"]
    for k in search_kinds:
        try:
            df = fetch_ths_board_members(k, name, limit=limit)
            if df is not None and not df.empty:
                col = "纯代码" if "纯代码" in df.columns else "代码"
                members = []
                for _, m in df.head(limit).iterrows():
                    code = str(m.get(col) or "").zfill(6)
                    if not code.isdigit():
                        continue
                    members.append(
                        {
                            "代码": code,
                            "名称": str(m.get("名称") or names.get(code) or stock_name_of(code)),
                            "现价": _clean(m.get("现价")),
                            "涨跌幅": _clean(m.get("涨跌幅")),
                            "成交额": _clean(m.get("成交额")),
                            "换手率": _clean(m.get("换手率")),
                        }
                    )
                if members:
                    _MEMBERS_CODE_CACHE[name] = [m["代码"] for m in members]
                    return {
                        "name": name,
                        "source": f"同花顺{k}",
                        "members": members,
                        "count": len(members),
                    }
        except Exception:
            continue
    return None


def fetch_concept_member_rows(
    name: str, *, limit: int = 80, kind: str = "概念"
) -> dict[str, Any]:
    """下钻成分股（极速版：120s缓存 → 内存索引+新浪现价 ~100ms → 同花顺单页 ~200ms，不阻塞在东财）。"""
    name = str(name or "").strip()
    if not name:
        return {"name": "", "source": "", "members": [], "count": 0, "error": "板块名为空"}

    now = time.time()
    cache_key = f"{kind}:{name}:{limit}"
    hit = _MEMBERS_ROW_CACHE.get(cache_key)
    if hit and (now - hit[0]) < _MEMBERS_CACHE_TTL:
        return hit[1]

    from .concept_leaders import _stock_name_map
    from .tdx import lookup_member_codes

    names = _stock_name_map()

    # 1. 极速通道：内存成分股索引（0ms，含同义词+二元分词100%覆盖）+ 新浪单次批量现价（~100ms）
    codes = (
        _MEMBERS_CODE_CACHE.get(name)
        or lookup_member_codes(kind, name)
        or lookup_member_codes("行业" if kind == "概念" else "概念", name)
    )
    if codes:
        _MEMBERS_CODE_CACHE[name] = codes
        sample_codes = codes[:limit]
        quotes: dict[str, dict[str, Any]] = {}
        try:
            from .metrics import fetch_member_quotes_sina

            quotes = fetch_member_quotes_sina(sample_codes)
        except Exception:
            quotes = {}
        members = []
        for code in sample_codes:
            q = quotes.get(code) or {}
            members.append(
                {
                    "代码": code,
                    "名称": names.get(code) or code,
                    "现价": q.get("price"),
                    "涨跌幅": q.get("chgPct"),
                    "成交额": q.get("amount"),
                    "换手率": None,
                }
            )
        members.sort(key=lambda x: float(x.get("涨跌幅") if x.get("涨跌幅") is not None else -999.0), reverse=True)
        res = {
            "name": name,
            "source": f"实时行情·{kind}",
            "members": members,
            "count": len(codes),
        }
        _MEMBERS_ROW_CACHE[cache_key] = (now, res)
        return res

    # 2. 同花顺成分页优先（不使用 with ThreadPoolExecutor 避免退出时阻塞）
    fut_ths = _LIVE_POOL.submit(_fetch_ths_members_rows, name, kind, limit, names)
    try:
        ths_res = fut_ths.result(timeout=2.0)
        if ths_res and ths_res.get("members"):
            _MEMBERS_ROW_CACHE[cache_key] = (now, ths_res)
            return ths_res
    except Exception:
        pass

    # 3. 东财可用时才尝试东财兜底
    em_res = _fetch_em_members_rows(name, limit, names)
    if em_res and em_res.get("members"):
        _MEMBERS_ROW_CACHE[cache_key] = (now, em_res)
        return em_res

    return {
        "name": name,
        "source": "",
        "members": [],
        "count": 0,
        "error": f"找不到「{name}」成分股",
    }


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
    """成分股/龙头现价：优先新浪单次批量 HTTP（~100ms），避免 pytdx 连接超时。"""
    if not codes:
        return {}
    from .metrics import fetch_member_quotes_sina

    try:
        raw = fetch_member_quotes_sina([str(c).zfill(6) for c in codes])
        if raw:
            return {
                c: {
                    "code": c,
                    "price": v.get("price"),
                    "chgPct": v.get("chgPct"),
                    "amount": v.get("amount"),
                }
                for c, v in raw.items()
            }
    except Exception:
        pass
    if tdx_hq_available():
        try:
            out = _quotes_from_tdx(codes)
            if out:
                return out
        except Exception:
            pass
    return {}


def concept_index_quote(name: str, today_map: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    row = today_map.get(name)
    if not row:
        for cand in candidate_concept_names(name):
            if cand in today_map:
                row = today_map[cand]
                break
    if not row:
        meta = resolve_concept_by_name(name)
        if meta:
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
