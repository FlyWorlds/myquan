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


def _has_valuation(payload: dict[str, Any]) -> bool:
    val = payload.get("valuation")
    if not isinstance(val, dict):
        return False
    return any(
        val.get(k) is not None
        for k in ("market_cap_yi", "float_cap_yi", "pe", "pe_ttm", "pb")
    )


_DOC_KEY = "stock_profiles"
_DB_PROFILES: dict[str, dict[str, Any]] | None = None
_DB_PROFILES_LOADED_AT: float = 0.0


def _db_enabled() -> bool:
    try:
        from database_holdings import database_enabled

        return database_enabled()
    except Exception:
        return False


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _load_db_profiles(*, force: bool = False) -> dict[str, dict[str, Any]]:
    global _DB_PROFILES, _DB_PROFILES_LOADED_AT
    now = time.time()
    if not force and _DB_PROFILES is not None and (now - _DB_PROFILES_LOADED_AT) < 60:
        return _DB_PROFILES

    loaded: dict[str, dict[str, Any]] = {}
    if _db_enabled():
        try:
            from runtime_documents import read_document

            _rev, payload = read_document(_DOC_KEY)
            if isinstance(payload, dict) and isinstance(payload.get("profiles"), dict):
                loaded = payload["profiles"]
        except Exception:
            pass
    if not loaded:
        local_cache = _ROOT / "holdingStocks/cache/stock_profiles.json"
        if local_cache.is_file():
            try:
                import json

                payload = json.loads(local_cache.read_text(encoding="utf-8"))
                if isinstance(payload, dict) and isinstance(payload.get("profiles"), dict):
                    loaded = payload["profiles"]
            except Exception:
                pass
    with _LOCK:
        _DB_PROFILES = loaded
        _DB_PROFILES_LOADED_AT = now
    return loaded


def _save_db_profile(code: str, payload: dict[str, Any]) -> None:
    """持久化单只股票画像到数据库。"""
    c = normalize_stock_code(code)
    if not c or not isinstance(payload, dict):
        return
    rec = dict(payload)
    rec["_cached_date"] = _today_str()

    current = dict(_load_db_profiles())
    current[c] = rec

    doc = {
        "updated_date": _today_str(),
        "profiles": current,
    }
    with _LOCK:
        global _DB_PROFILES, _DB_PROFILES_LOADED_AT
        _DB_PROFILES = current
        _DB_PROFILES_LOADED_AT = time.time()

    if _db_enabled():
        try:
            from runtime_documents import write_merging

            write_merging(_DOC_KEY, doc)
            return
        except Exception:
            pass
    try:
        local_cache = _ROOT / "holdingStocks/cache/stock_profiles.json"
        local_cache.parent.mkdir(parents=True, exist_ok=True)
        import json

        local_cache.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _cache_get(code: str) -> dict[str, Any] | None:
    with _LOCK:
        hit = _CACHE.get(code)
        if hit:
            ts, payload = hit
            ttl = _CACHE_TTL_SEC if _has_valuation(payload) else 5.0
            if time.time() - ts <= ttl:
                return payload
            _CACHE.pop(code, None)

    # 查数据库中的当日记录（若今天已有有效估值，直接命中）
    db_profiles = _load_db_profiles()
    p = db_profiles.get(code)
    if p and p.get("_cached_date") == _today_str() and _has_valuation(p):
        with _LOCK:
            _CACHE[code] = (time.time(), p)
        return p
    return None


def _cache_put(code: str, payload: dict[str, Any]) -> None:
    with _LOCK:
        _CACHE[code] = (time.time(), payload)
    if _has_valuation(payload):
        threading.Thread(target=_save_db_profile, args=(code, payload), daemon=True).start()


def daily_sync_stock_profiles(codes: list[str] | None = None) -> int:
    """每天启动后在后台异步执行一次：将监控池股票画像及行情记录入库。

    完全不阻塞系统启动；今天已同步过的数据直接跳过，零重复网络消耗。
    """
    target_codes: list[str] = []
    seen: set[str] = set()
    for raw in (codes or []):
        c = normalize_stock_code(raw)
        if c and c not in seen:
            seen.add(c)
            target_codes.append(c)

    if not target_codes:
        return 0

    today = _today_str()
    db_profiles = _load_db_profiles(force=True)

    pending = [
        c
        for c in target_codes
        if not (
            db_profiles.get(c)
            and db_profiles[c].get("_cached_date") == today
            and _has_valuation(db_profiles[c])
        )
    ]

    if not pending:
        return len(target_codes)

    updated = 0
    batch_map = dict(db_profiles)
    for c in pending:
        try:
            p = get_stock_profile(c, use_cache=False)
            if p and not p.get("error"):
                rec = dict(p)
                rec["_cached_date"] = today
                batch_map[c] = rec
                updated += 1
            time.sleep(0.15)
        except Exception:
            continue

    if updated > 0:
        doc = {
            "updated_date": today,
            "profiles": batch_map,
        }
        with _LOCK:
            global _DB_PROFILES, _DB_PROFILES_LOADED_AT
            _DB_PROFILES = batch_map
            _DB_PROFILES_LOADED_AT = time.time()
        if _db_enabled():
            try:
                from runtime_documents import write_merging

                write_merging(_DOC_KEY, doc)
            except Exception:
                pass
        try:
            local_cache = _ROOT / "holdingStocks/cache/stock_profiles.json"
            local_cache.parent.mkdir(parents=True, exist_ok=True)
            import json

            local_cache.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    return updated


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


def _infer_market_label(code: str) -> str | None:
    c = normalize_stock_code(code)
    if not c:
        return None
    if c.startswith(("688", "689")):
        return "上交所科创板A股"
    if c.startswith(("6", "9")):
        return "上交所主板A股"
    if c.startswith(("300", "301")):
        return "深交所创业板A股"
    if c.startswith(("00", "002", "003")):
        return "深交所主板A股"
    if c.startswith(("8", "4", "92")):
        return "北交所A股"
    return None


def _fetch_survey_em(code: str) -> dict[str, Any]:
    url = (
        "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/"
        f"CompanySurveyAjax?code={em_f10_code(code)}"
    )
    r = requests.get(url, headers=_EM_HEADERS, timeout=2.2)
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


def _fetch_survey_sina(code: str) -> dict[str, Any]:
    """新浪 F10 公司简介兜底（当东财 emweb 在海外/受限网络超时或连接重置时启用）。"""
    import html
    import re

    c = normalize_stock_code(code)
    if not c:
        return {}
    url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpInfo/stockid/{c}.phtml"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://finance.sina.com.cn/",
    }
    r = requests.get(url, headers=headers, timeout=2.5)
    r.raise_for_status()
    text = r.content.decode("gb18030", errors="ignore")
    cells = re.findall(r"<td[^>]*>(.*?)</td>", text, flags=re.S | re.I)
    cleaned: list[str] = []
    for raw in cells:
        plain = re.sub(r"<[^>]+>", " ", raw)
        plain = html.unescape(plain)
        plain = " ".join(plain.split())
        cleaned.append(plain)
    kv: dict[str, str] = {}
    for i in range(len(cleaned) - 1):
        k = cleaned[i].rstrip("：:").strip()
        v = cleaned[i + 1].strip()
        if k and v and len(k) <= 16 and k not in kv:
            kv[k] = v
    return {
        "full_name": _blank(kv.get("公司名称")),
        "market": _blank(kv.get("上市市场")) or _infer_market_label(c),
        "list_date": _blank(kv.get("上市日期")),
        "registered_capital": _blank(kv.get("注册资本")),
        "region": _blank(kv.get("所属地区")) or _blank(kv.get("办公地址")),
        "chairman": _blank(kv.get("董事长")) or _blank(kv.get("法人代表")),
        "summary": _clip(kv.get("公司简介"), 280),
        "business_scope": _clip(kv.get("经营范围"), 220),
        "website": _blank(kv.get("公司网址")),
    }


def _fetch_survey(code: str) -> dict[str, Any]:
    c = normalize_stock_code(code)
    out: dict[str, Any] = {}
    try:
        out = _fetch_survey_em(c)
    except Exception:
        out = {}
    if not out.get("full_name") and not out.get("summary"):
        try:
            sina_survey = _fetch_survey_sina(c)
            for k, v in sina_survey.items():
                if v is not None and not out.get(k):
                    out[k] = v
        except Exception:
            pass
    if not out.get("market"):
        out["market"] = _infer_market_label(c)
    return out


def _fetch_quote_tencent(code: str) -> dict[str, Any]:
    """腾讯行情接口（http://qt.gtimg.cn）：单次请求返回总市值/流通市值/PE(动)/PE(TTM)/PB/涨跌幅。"""
    sina = _sina_of(code).lower()
    # 优先 http 避免代理及特定 macOS 环境下 TLS 握手的 SSLEOFError
    urls = [f"http://qt.gtimg.cn/q={sina}", f"https://qt.gtimg.cn/q={sina}"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "http://gu.qq.com/",
    }
    text = ""
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=2.2)
            if r.status_code == 200 and '="' in r.text:
                text = r.content.decode("gbk", errors="ignore").strip()
                break
        except Exception:
            continue
    if not text or '="' not in text:
        return {}
    payload = text.split('="', 1)[1].rstrip('";')
    parts = payload.split("~")
    if len(parts) < 33:
        return {}
    price = _num(parts[3])
    prev = _num(parts[4])
    chg = _num(parts[32])
    if chg is None and price is not None and prev is not None and prev > 0:
        chg = round((price / prev - 1.0) * 100.0, 2)
    pe_ttm = _num(parts[39]) if len(parts) > 39 else None
    float_cap = _num(parts[44]) if len(parts) > 44 else None
    market_cap = _num(parts[45]) if len(parts) > 45 else None
    pb = _num(parts[46]) if len(parts) > 46 else None
    pe_dyn = _num(parts[52]) if len(parts) > 52 else None
    pe_stat = _num(parts[53]) if len(parts) > 53 else None
    return {
        "name": _blank(parts[1]) if len(parts) > 1 else None,
        "price": price,
        "chg_pct": chg,
        "market_cap_yi": round(market_cap, 2) if market_cap and market_cap > 0 else None,
        "float_cap_yi": round(float_cap, 2) if float_cap and float_cap > 0 else None,
        "pe": pe_dyn if pe_dyn is not None else pe_ttm,
        "pe_ttm": pe_ttm if pe_ttm is not None else pe_stat,
        "pb": pb,
    }


def _fetch_quote_em(code: str) -> dict[str, Any]:
    secid = sina_to_secid(_sina_of(code))
    urls = [
        f"http://push2delay.eastmoney.com/api/qt/stock/get?secid={secid}&fltt=2&invt=2&fields=f57,f58,f43,f44,f45,f46,f168,f169,f170,f116,f117,f84,f85,f162,f167,f9,f23,f115,f20,f21",
        f"http://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&fields=f12,f14,f2,f3,f9,f20,f21,f23,f115&secids={secid}",
        f"https://2.push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&fields=f12,f14,f2,f3,f9,f20,f21,f23,f115&secids={secid}",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=_QUOTE_HEADERS, timeout=2.2)
            if r.status_code != 200:
                continue
            data = r.json()
            d = data.get("data")
            if not d:
                continue
            if isinstance(d, dict) and "diff" in d:
                rows = d.get("diff") or []
                row = rows[0] if rows else {}
                name = _blank(row.get("f14"))
                price = _num(row.get("f2"))
                chg = _num(row.get("f3"))
                mcap = _yi(row.get("f20"))
                fcap = _yi(row.get("f21"))
                pe = _num(row.get("f9"))
                pe_ttm = _num(row.get("f115"))
                pb = _num(row.get("f23"))
            elif isinstance(d, dict):
                name = _blank(d.get("f58"))
                price = _num(d.get("f43"))
                chg = _num(d.get("f170"))
                mcap = _yi(d.get("f20")) or _yi(d.get("f116"))
                fcap = _yi(d.get("f21")) or _yi(d.get("f117"))
                pe = _num(d.get("f9")) or _num(d.get("f162"))
                pe_ttm = _num(d.get("f115")) or _num(d.get("f167"))
                pb = _num(d.get("f23")) or _num(d.get("f168"))
            else:
                continue
            return {
                "name": name,
                "price": price,
                "chg_pct": chg,
                "market_cap_yi": mcap,
                "float_cap_yi": fcap,
                "pe": pe,
                "pe_ttm": pe_ttm,
                "pb": pb,
            }
        except Exception:
            continue
    return {}


def _fetch_quote_sina_node(code: str) -> dict[str, Any]:
    """新浪行情中心接口：包含 mktcap(总市值万元), nmc(流通市值万元), per(PE), pb(PB)。"""
    sina = _sina_of(code).lower()
    url = (
        "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"Market_Center.getHQNodeData?page=1&num=1&sort=symbol&asc=1&node=hs_a&symbol={sina}"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "http://vip.stock.finance.sina.com.cn/",
    }
    try:
        r = requests.get(url, headers=headers, timeout=2.5)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data:
            row = data[0]
            mktcap_yi = _num(row.get("mktcap"))
            if mktcap_yi is not None and mktcap_yi > 0:
                mktcap_yi = round(mktcap_yi / 10000.0, 2)
            nmc_yi = _num(row.get("nmc"))
            if nmc_yi is not None and nmc_yi > 0:
                nmc_yi = round(nmc_yi / 10000.0, 2)
            pe_val = _num(row.get("per"))
            return {
                "name": _blank(row.get("name")),
                "price": _num(row.get("trade")),
                "chg_pct": _num(row.get("changepercent")),
                "market_cap_yi": mktcap_yi,
                "float_cap_yi": nmc_yi,
                "pe": pe_val,
                "pe_ttm": pe_val,
                "pb": _num(row.get("pb")),
            }
    except Exception:
        pass
    return {}


def _fetch_quote_sina_fallback(code: str) -> dict[str, Any]:
    from quote_feed import fetch_sina_batch

    sina = _sina_of(code).lower()
    batch = fetch_sina_batch([sina], timeout=2.5)
    spot = batch.get(sina) or {}
    if not spot:
        return {}
    return {
        "name": _blank(spot.get("name")),
        "price": _num(spot.get("last")),
        "chg_pct": _num(spot.get("day_chg_pct")),
    }


def _fetch_quote(code: str) -> dict[str, Any]:
    c = normalize_stock_code(code)
    out: dict[str, Any] = {}
    try:
        out = _fetch_quote_tencent(c)
    except Exception:
        out = {}
    if not any(out.get(k) is not None for k in ("market_cap_yi", "pe", "pb")):
        try:
            em_q = _fetch_quote_em(c)
            for k, v in em_q.items():
                if v is not None and out.get(k) is None:
                    out[k] = v
        except Exception:
            pass
    if not any(out.get(k) is not None for k in ("market_cap_yi", "pe", "pb")):
        try:
            sina_node = _fetch_quote_sina_node(c)
            for k, v in sina_node.items():
                if v is not None and out.get(k) is None:
                    out[k] = v
        except Exception:
            pass
    if out.get("price") is None or out.get("chg_pct") is None:
        try:
            sina_q = _fetch_quote_sina_fallback(c)
            for k, v in sina_q.items():
                if v is not None and out.get(k) is None:
                    out[k] = v
        except Exception:
            pass
    return out


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


def _is_real_name(code: str, name: Any) -> bool:
    c = normalize_stock_code(code)
    n = str(name or "").strip()
    if not c or not n:
        return False
    if n == c or n.isdigit():
        return False
    return True


def _local_name_table() -> dict[str, str]:
    """全量本地名称表。不走逐码网络，避免 hover 只补到大板块前 80 只。"""
    out: dict[str, str] = {}
    try:
        from stock_names import name_by_code

        for raw, name in name_by_code().items():
            c = normalize_stock_code(raw) or str(raw).zfill(6)
            if _is_real_name(c, name):
                out[c] = str(name).strip()
    except Exception:
        pass
    try:
        from sectors.stock_names import stock_name_map

        for raw, name in stock_name_map().items():
            c = normalize_stock_code(raw) or str(raw).zfill(6)
            if c not in out and _is_real_name(c, name):
                out[c] = str(name).strip()
    except Exception:
        pass
    return out


def _secid(code: str) -> str:
    c = normalize_stock_code(code)
    if not c:
        return ""
    if c.startswith(("6", "5")) or (c.startswith("9") and not c.startswith(("92", "43"))):
        return f"1.{c}"
    return f"0.{c}"


def _fetch_names_ulist(codes: list[str]) -> dict[str, str]:
    """批量补中文名（优先新浪批量快照，东财 2.push2 兜底）。"""
    out: dict[str, str] = {}
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in codes:
        c = normalize_stock_code(raw)
        if c and c not in seen:
            seen.add(c)
            cleaned.append(c)
    if not cleaned:
        return out
    try:
        from quote_feed import fetch_sina_batch

        batch = fetch_sina_batch([_sina_of(c) for c in cleaned], timeout=2.5)
        for sina, spot in (batch or {}).items():
            c = normalize_stock_code(sina)
            n = _blank((spot or {}).get("name"))
            if c and _is_real_name(c, n):
                out[c] = str(n)
    except Exception:
        pass
    remaining = [c for c in cleaned if c not in out]
    for i in range(0, len(remaining), 40):
        chunk = remaining[i : i + 40]
        secids = ",".join(s for s in (_secid(c) for c in chunk) if s)
        if not secids:
            continue
        try:
            url = (
                "https://2.push2.eastmoney.com/api/qt/ulist.np/get"
                f"?fltt=2&invt=2&fields=f12,f14&secids={secids}"
            )
            r = requests.get(url, headers=_QUOTE_HEADERS, timeout=2.2)
            r.raise_for_status()
            rows = ((r.json() or {}).get("data") or {}).get("diff") or []
        except Exception:
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            c = normalize_stock_code(str(row.get("f12") or ""))
            n = _blank(row.get("f14"))
            if c and _is_real_name(c, n):
                out[c] = str(n)
    if out:
        try:
            from stock_names import _remember_name

            for c, n in out.items():
                _remember_name(c, n)
        except Exception:
            pass
    return out


def _apply_names(rows: list[dict[str, Any]], names: dict[str, str]) -> None:
    for r in rows:
        c = str(r.get("code") or "")
        n = names.get(c)
        if _is_real_name(c, n):
            r["name"] = n


def _name_map(codes: list[str]) -> dict[str, str]:
    table = _local_name_table()
    out = {c: table[c] for c in (normalize_stock_code(x) for x in codes) if c and c in table}
    missing = [normalize_stock_code(x) for x in codes if normalize_stock_code(x) not in out]
    missing = [c for c in missing if c]
    if missing:
        out.update(_fetch_names_ulist(missing))
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

    names = _local_name_table()
    related = _related_from_boards(c, boards, idx, names)
    missing = [r["code"] for r in related if not _is_real_name(r["code"], r.get("name"))]
    if not _is_real_name(c, names.get(c)):
        missing.append(c)
    if missing:
        names.update(_fetch_names_ulist(missing))
        _apply_names(related, names)

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
    # 算法兜底：若外网所有行情接口均未能返回总市值，但拿到了现价与注册资本(总股本)
    val = payload["valuation"]
    if val.get("market_cap_yi") is None and val.get("price") is not None:
        cap_str = str((survey or {}).get("registered_capital") or "")
        import re
        m = re.search(r"([\d\.]+)\s*(万|亿)?", cap_str)
        if m:
            try:
                num = float(m.group(1))
                unit = m.group(2)
                shares_yi = (num / 10000.0) if unit == "万" else num if unit == "亿" else (num / 1e8 if num > 1e7 else num)
                if shares_yi > 0:
                    est_mcap = round(val["price"] * shares_yi, 2)
                    if est_mcap > 0:
                        val["market_cap_yi"] = est_mcap
            except Exception:
                pass
    if use_cache and fetch_survey is None and members_index is None:
        _cache_put(c, payload)
    return payload
