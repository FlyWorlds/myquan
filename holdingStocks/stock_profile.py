"""个股 hover 画像：通达信板块反查 + 东财 F10/估值 + 同板块关联。"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable

import requests

from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from quote_feed import sina_to_secid

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SEC = 30 * 60
_REV: dict[str, dict[str, list[str]]] | None = None
_REV_KEY: tuple[int, int] | None = None

_EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://emweb.securities.eastmoney.com/",
}
_QUOTE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
}

_CHAIN_UP = ("上游", "原材料", "锂矿", "硅料", "设备", "芯片材料")
_CHAIN_DOWN = ("下游", "整车", "消费电子", "应用端", "终端")
_CHAIN_LINK = ("产业链", "产业")


def normalize_stock_code(raw: str | None) -> str:
    s = str(raw or "").strip().lower()
    if s.startswith(("sh", "sz", "bj")):
        s = s[2:]
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) < 6:
        return ""
    return digits[-6:]


def em_f10_code(code: str) -> str:
    c = normalize_stock_code(code)
    if c.startswith("6"):
        return f"SH{c}"
    if c.startswith(("92", "43", "83", "87", "88")):
        return f"BJ{c}"
    if c.startswith("9"):
        return f"SH{c}"
    return f"SZ{c}"


def _sina_of(code: str) -> str:
    c = normalize_stock_code(code)
    if c.startswith(("6", "5")):
        return f"sh{c}"
    if c.startswith("9") and not c.startswith(("92", "43")):
        return f"sh{c}"
    return f"sz{c}"


def _blank(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, str):
        t = v.strip()
        if not t or t in {"--", "-", "—", "null", "None"}:
            return None
        return t
    return v


def _num(v: Any) -> float | None:
    v = _blank(v)
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def _yi(v: Any) -> float | None:
    x = _num(v)
    if x is None or x <= 0:
        return None
    return round(x / 1e8, 2)


def _clip(text: str | None, n: int) -> str | None:
    t = _blank(text)
    if not t:
        return None
    t = " ".join(str(t).split())
    if len(t) <= n:
        return t
    return t[: n - 1] + "…"


def clear_profile_cache() -> None:
    with _LOCK:
        _CACHE.clear()


def _cache_get(code: str) -> dict[str, Any] | None:
    with _LOCK:
        hit = _CACHE.get(code)
        if not hit:
            return None
        ts, payload = hit
        if time.time() - ts > _CACHE_TTL_SEC:
            _CACHE.pop(code, None)
            return None
        return payload


def _cache_put(code: str, payload: dict[str, Any]) -> None:
    with _LOCK:
        _CACHE[code] = (time.time(), payload)


def warm_profile_index() -> int:
    """盯盘冷启动预建板块反查，避免第一次 hover 卡在通达信索引。"""
    return len(_reverse_index())


def _reverse_index(
    members_index: dict[str, dict[str, list[str]]] | None = None,
) -> dict[str, dict[str, list[str]]]:
    global _REV, _REV_KEY
    if members_index is not None:
        return _build_reverse(members_index)
    try:
        from sectors.tdx import load_members_index

        idx = load_members_index()
    except Exception:
        return {}
    ind = idx.get("行业") or {}
    con = idx.get("概念") or {}
    key = (len(ind), len(con))
    with _LOCK:
        if _REV is not None and _REV_KEY == key:
            return _REV
        built = _build_reverse(idx)
        _REV = built
        _REV_KEY = key
        return built


def _build_reverse(idx: dict[str, dict[str, list[str]]]) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for kind in ("行业", "概念"):
        for name, members in (idx.get(kind) or {}).items():
            board = str(name or "").strip()
            if not board:
                continue
            for raw in members or []:
                c = normalize_stock_code(str(raw))
                if not c:
                    continue
                rec = out.setdefault(c, {"行业": [], "概念": []})
                if board not in rec[kind]:
                    rec[kind].append(board)
    return out


def _chain_role(board: str) -> str | None:
    n = str(board or "")
    if any(k in n for k in _CHAIN_UP):
        return "上游"
    if any(k in n for k in _CHAIN_DOWN):
        return "下游"
    if any(k in n for k in _CHAIN_LINK):
        return "产业链"
    return None


def _related_from_boards(
    code: str,
    boards: dict[str, list[str]],
    members_index: dict[str, dict[str, list[str]]],
    names: dict[str, str],
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen = {code}

    def _take(kind: str, board: str, cap: int) -> None:
        nonlocal out
        if len(out) >= limit:
            return
        members = (members_index.get(kind) or {}).get(board) or []
        named: list[str] = []
        unnamed: list[str] = []
        for raw in members:
            c = normalize_stock_code(str(raw))
            if not c or c in seen:
                continue
            if names.get(c) and names[c] != c:
                named.append(c)
            else:
                unnamed.append(c)
        n = 0
        for c in named + unnamed:
            if n >= cap or len(out) >= limit:
                break
            seen.add(c)
            role = _chain_role(board)
            relation = f"同{kind}"
            if role:
                relation = f"同{role}"
            out.append(
                {
                    "code": c,
                    "name": names.get(c) or c,
                    "relation": relation,
                    "board": board,
                    "kind": kind,
                    "role": role,
                }
            )
            n += 1

    for board in (boards.get("行业") or [])[:2]:
        _take("行业", board, 3)
    concepts = list(boards.get("概念") or [])
    sized = sorted(
        concepts,
        key=lambda b: len((members_index.get("概念") or {}).get(b) or []),
    )
    for board in sized[:8]:
        _take("概念", board, 2)
    return out


def _fetch_survey(code: str) -> dict[str, Any]:
    url = (
        "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/"
        f"CompanySurveyAjax?code={em_f10_code(code)}"
    )
    r = requests.get(url, headers=_EM_HEADERS, timeout=4)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        return {}
    jb = data.get("jbzl") if isinstance(data.get("jbzl"), dict) else {}
    fx = data.get("fxxg") if isinstance(data.get("fxxg"), dict) else {}
    return {
        "name": _blank(jb.get("agjc")) or _blank(data.get("SecurityShortName")),
        "full_name": _blank(jb.get("gsmc")),
        "market": _blank(jb.get("zqlb")),
        "industry": _blank(jb.get("sshy")),
        "csrc_industry": _blank(jb.get("sszjhhy")),
        "region": _blank(jb.get("qy")),
        "chairman": _blank(jb.get("dsz")),
        "employees": _blank(jb.get("gyrs")),
        "registered_capital": _blank(jb.get("zczb")),
        "list_date": _blank(fx.get("ssrq")),
        "summary": _clip(jb.get("gsjj"), 280),
        "business_scope": _clip(jb.get("jyfw"), 220),
        "website": _blank(jb.get("gswz")),
    }


def _fetch_quote(code: str) -> dict[str, Any]:
    secid = sina_to_secid(_sina_of(code))
    url = (
        "https://2.push2.eastmoney.com/api/qt/ulist.np/get"
        f"?fltt=2&invt=2&fields=f12,f14,f2,f3,f9,f20,f21,f23,f115&secids={secid}"
    )
    r = requests.get(url, headers=_QUOTE_HEADERS, timeout=4)
    r.raise_for_status()
    data = r.json()
    rows = ((data or {}).get("data") or {}).get("diff") or []
    row = rows[0] if rows else {}
    return {
        "name": _blank(row.get("f14")),
        "price": _num(row.get("f2")),
        "chg_pct": _num(row.get("f3")),
        "market_cap_yi": _yi(row.get("f20")),
        "float_cap_yi": _yi(row.get("f21")),
        "pe": _num(row.get("f9")),
        "pe_ttm": _num(row.get("f115")),
        "pb": _num(row.get("f23")),
    }


def _fetch_core_themes(code: str) -> list[dict[str, str]]:
    url = (
        "https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/"
        f"CoreConceptionAjax?code={em_f10_code(code)}&type=web"
    )
    r = requests.get(url, headers=_EM_HEADERS, timeout=6)
    if r.status_code != 200:
        return []
    try:
        data = r.json()
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    rows = data.get("hxtc") or data.get("ssbk") or []
    out: list[dict[str, str]] = []
    if isinstance(rows, list):
        for item in rows:
            if not isinstance(item, dict):
                continue
            name = _blank(item.get("gjc") or item.get("BOARD_NAME") or item.get("name"))
            if not name:
                continue
            desc = _clip(item.get("yd") or item.get("ydnr") or item.get("desc"), 80)
            out.append({"name": str(name), "desc": desc or ""})
    return out[:12]


def _name_map(codes: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        from stock_names import lookup_names_for_codes

        out.update(lookup_names_for_codes(codes))
    except Exception:
        pass
    missing = [c for c in codes if c not in out]
    if not missing:
        return out
    try:
        from sectors.stock_names import stock_name_map

        table = stock_name_map()
        for c in missing:
            n = str(table.get(c) or "").strip()
            if n:
                out[c] = n
    except Exception:
        pass
    return out


def get_stock_profile(
    code: str,
    *,
    fetch_survey: Callable[[str], dict[str, Any]] | None = None,
    fetch_quote: Callable[[str], dict[str, Any]] | None = None,
    fetch_themes: Callable[[str], list[dict[str, str]]] | None = None,
    members_index: dict[str, dict[str, list[str]]] | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """聚合一只股票的基本面画像。网络失败时返回本地板块部分，不抛给 HTTP。"""
    c = normalize_stock_code(code)
    if not c:
        return {"error": "invalid code", "code": code}
    if use_cache and fetch_survey is None and members_index is None:
        hit = _cache_get(c)
        if hit is not None:
            return hit

    rev = _reverse_index(members_index)
    boards = rev.get(c) or {"行业": [], "概念": []}
    idx = members_index
    if idx is None:
        try:
            from sectors.tdx import load_members_index

            idx = load_members_index()
        except Exception:
            idx = {"行业": {}, "概念": {}}

    survey_fn = fetch_survey or _fetch_survey
    quote_fn = fetch_quote or _fetch_quote
    # 东财核心题材页经常不是 JSON，默认跳过以免拖慢 hover
    themes_fn = fetch_themes

    survey: dict[str, Any] = {}
    quote: dict[str, Any] = {}
    themes: list[dict[str, str]] = []
    errors: list[str] = []

    def _call(label: str, fn: Callable[[], Any], default: Any) -> Any:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}:{type(exc).__name__}")
            return default

    if fetch_survey is not None or fetch_quote is not None or fetch_themes is not None:
        survey = _call("survey", lambda: survey_fn(c), {})
        quote = _call("quote", lambda: quote_fn(c), {})
        if themes_fn is not None:
            themes = _call("themes", lambda: themes_fn(c), [])
    else:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_s = pool.submit(_call, "survey", lambda: survey_fn(c), {})
            f_q = pool.submit(_call, "quote", lambda: quote_fn(c), {})
            survey = f_s.result()
            quote = f_q.result()

    industry_boards = list(boards.get("行业") or [])
    concept_boards = list(boards.get("概念") or [])
    em_hy = (survey or {}).get("industry")
    if em_hy and em_hy not in industry_boards:
        if em_hy in (idx.get("行业") or {}):
            industry_boards.insert(0, em_hy)
            boards = {
                **boards,
                "行业": industry_boards
                + [b for b in (boards.get("行业") or []) if b not in industry_boards],
            }
    theme_names = [t["name"] for t in themes if t.get("name")]
    for name in theme_names:
        if name not in concept_boards:
            concept_boards.append(name)

    related_seed_codes: list[str] = []
    for kind in ("行业", "概念"):
        for board in (boards.get(kind) or [])[:10]:
            related_seed_codes.extend((idx.get(kind) or {}).get(board) or [])
    uniq = []
    seen_c = set()
    for raw in related_seed_codes:
        cc = normalize_stock_code(str(raw))
        if cc and cc not in seen_c:
            seen_c.add(cc)
            uniq.append(cc)
    names = _name_map([c, *uniq[:80]])
    related = _related_from_boards(c, boards, idx, names)

    upstream = [r for r in related if r.get("role") == "上游"]
    downstream = [r for r in related if r.get("role") == "下游"]
    mid = [r for r in related if r.get("role") == "产业链"]

    name = (
        (survey or {}).get("name")
        or (quote or {}).get("name")
        or names.get(c)
        or c
    )
    payload = {
        "code": c,
        "name": name,
        "full_name": (survey or {}).get("full_name"),
        "market": (survey or {}).get("market"),
        "industry": (survey or {}).get("industry") or (industry_boards[0] if industry_boards else None),
        "csrc_industry": (survey or {}).get("csrc_industry"),
        "region": (survey or {}).get("region"),
        "chairman": (survey or {}).get("chairman"),
        "employees": (survey or {}).get("employees"),
        "registered_capital": (survey or {}).get("registered_capital"),
        "list_date": (survey or {}).get("list_date"),
        "summary": (survey or {}).get("summary"),
        "business_scope": (survey or {}).get("business_scope"),
        "website": (survey or {}).get("website"),
        "valuation": {
            "price": (quote or {}).get("price"),
            "chg_pct": (quote or {}).get("chg_pct"),
            "market_cap_yi": (quote or {}).get("market_cap_yi"),
            "float_cap_yi": (quote or {}).get("float_cap_yi"),
            "pe": (quote or {}).get("pe"),
            "pe_ttm": (quote or {}).get("pe_ttm"),
            "pb": (quote or {}).get("pb"),
        },
        "boards": {
            "industry": industry_boards,
            "concept": concept_boards[:24],
        },
        "themes": themes,
        "related": related,
        "chain": {
            "upstream": upstream,
            "midstream": mid,
            "downstream": downstream,
            "note": (survey or {}).get("business_scope"),
        },
        "sources": ["tdx_members", "eastmoney_f10", "eastmoney_quote"],
        "as_of": datetime.now().isoformat(timespec="seconds"),
        "errors": errors,
    }
    if use_cache and fetch_survey is None and members_index is None:
        _cache_put(c, payload)
    return payload
