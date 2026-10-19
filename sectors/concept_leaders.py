"""板块详情与波段龙头：近半年指数 K 线 + 上涨段成分股领涨统计。

极速优化（解决东财被墙/重置与 ThreadPoolExecutor.__exit__ 等待慢任务问题）：
1. 模块级常驻线程池 `_DETAIL_POOL`，杜绝 `with ThreadPoolExecutor` 在退出时调用 `shutdown(wait=True)` 等待慢请求超时
2. K 线优先直连同花顺静态 CDN（`d.10jqka.com.cn`，~150ms）；若无同花顺 clid，直接用成分股通过新浪高速日线接口（`CN_MarketData.getKLineData`，~100ms）合成板块指数 K 线
3. 个股日线改走新浪日线 JSON 接口（带进程内 30 分钟缓存），彻底绕开东财 `push2his.eastmoney.com` SSL 重置超时
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter

from .store import get_doc, make_doc_key, set_doc
from .tdx import (
    fetch_tdx_index_kline,
    fetch_tdx_stock_klines,
    lookup_member_codes,
    resolve_concept_by_name,
    tdx_hq_available,
)
from .ths import (
    candidate_concept_names,
    fetch_ths_board_kline,
    fetch_ths_board_members,
)

_DETAIL_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="sector-detail")
_STOCK_BARS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_STOCK_BARS_TTL = 1800.0

_SINA_SESSION: requests.Session | None = None


def _sina_http() -> requests.Session:
    global _SINA_SESSION
    if _SINA_SESSION is None:
        s = requests.Session()
        s.trust_env = False
        adapter = HTTPAdapter(pool_connections=24, pool_maxsize=24, max_retries=0)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Referer": "https://finance.sina.com.cn/",
            }
        )
        _SINA_SESSION = s
    return _SINA_SESSION


def _clean(v: Any) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        x = float(v)
        return None if pd.isna(x) else x
    except (TypeError, ValueError):
        return None


_NAME_MAP: dict[str, str] | None = None


def _stock_name_map() -> dict[str, str]:
    """零网络快速股票名称表。"""
    global _NAME_MAP
    if _NAME_MAP is not None:
        return _NAME_MAP
    try:
        from stock_names import name_by_code

        _NAME_MAP = dict(name_by_code())
    except Exception:
        _NAME_MAP = {}
    return _NAME_MAP


def _return_from_bars(
    bars: list[dict[str, Any]], start: str, end: str
) -> float | None:
    start_s, end_s = str(start)[:10], str(end)[:10]
    window = [b for b in bars if start_s <= str(b.get("date") or "")[:10] <= end_s]
    if len(window) < 2:
        return None
    o = _clean(window[0].get("open")) or _clean(window[0].get("close"))
    c = _clean(window[-1].get("close"))
    if not o or not c or o <= 0:
        return None
    return (c / o - 1.0) * 100.0


_DATA_CACHE_DIR = pd.io.common.stringify_path(
    __import__("pathlib").Path(__file__).resolve().parents[1] / "data_cache"
)


def _parquet_path_for(code: str) -> __import__("pathlib").Path:
    from pathlib import Path

    c = str(code).zfill(6)
    prefix = "sh" if c.startswith(("5", "6", "9")) else "sz"
    return Path(_DATA_CACHE_DIR) / f"{prefix}{c}_daily_qfq.parquet"


def _read_local_parquet_bars(code: str, *, count: int = 160) -> list[dict[str, Any]]:
    p = _parquet_path_for(code)
    if not p.is_file():
        return []
    try:
        df = pd.read_parquet(p)
        if df is None or df.empty:
            return []
        tail = df.tail(max(count, 60))
        out: list[dict[str, Any]] = []
        for _, r in tail.iterrows():
            dt = str(r.get("date") or "")[:10]
            c = _clean(r.get("close"))
            if not dt or c is None:
                continue
            out.append(
                {
                    "date": dt,
                    "open": _clean(r.get("open")) or c,
                    "high": _clean(r.get("high")) or c,
                    "low": _clean(r.get("low")) or c,
                    "close": c,
                    "vol": _clean(r.get("volume")),
                    "amount": None,
                }
            )
        return out[-count:] if len(out) >= 20 else []
    except Exception:
        return []


def _prioritize_cached_codes(codes: list[str], *, limit: int = 8) -> list[str]:
    clean_codes = [str(c).zfill(6) for c in codes if str(c).strip().isdigit()]
    local_hits = [c for c in clean_codes if _parquet_path_for(c).is_file()]
    if len(local_hits) >= limit:
        return local_hits[:limit]
    seen = set(local_hits)
    rest = [c for c in clean_codes if c not in seen]
    return (local_hits + rest)[:limit]


def _fetch_stock_kline_bars(code: str, *, count: int = 160) -> list[dict[str, Any]]:
    """优先读本地 data_cache parquet（<1ms），其次走新浪高速日线 JSON 接口（~80ms）。"""
    code = str(code).zfill(6)
    now = time.time()
    hit = _STOCK_BARS_CACHE.get(code)
    if hit and (now - hit[0]) < _STOCK_BARS_TTL and len(hit[1]) >= min(count, 30):
        return hit[1][-count:]

    # 0. 本地 data_cache parquet 极速命中（<1ms，零网络）
    local_bars = _read_local_parquet_bars(code, count=count)
    if local_bars:
        _STOCK_BARS_CACHE[code] = (now, local_bars)
        return local_bars

    # 1. 新浪日线 JSON 接口（本机实测 ~80ms，极速稳定）
    prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
    try:
        sess = _sina_http()
        r = sess.get(
            "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
            params={
                "symbol": f"{prefix}{code}",
                "scale": "240",
                "ma": "no",
                "datalen": str(max(count, 160)),
            },
            timeout=2.0,
        )
        if r.status_code == 200 and r.text:
            arr = json.loads(r.text)
            if isinstance(arr, list) and arr:
                out: list[dict[str, Any]] = []
                for item in arr:
                    if not isinstance(item, dict):
                        continue
                    dt = str(item.get("day") or "")[:10]
                    c = _clean(item.get("close"))
                    if not dt or c is None:
                        continue
                    out.append(
                        {
                            "date": dt,
                            "open": _clean(item.get("open")) or c,
                            "high": _clean(item.get("high")) or c,
                            "low": _clean(item.get("low")) or c,
                            "close": c,
                            "vol": _clean(item.get("volume")),
                            "amount": None,
                        }
                    )
                if out:
                    _STOCK_BARS_CACHE[code] = (now, out)
                    return out[-count:]
    except Exception:
        pass

    # 2. 通达信回退
    if tdx_hq_available():
        try:
            series = fetch_tdx_stock_klines([code], count=count).get(code) or []
            if series:
                _STOCK_BARS_CACHE[code] = (now, series)
                return series
        except Exception:
            pass

    return []


def _synthesize_kline_from_members(
    codes: list[str], *, count: int = 130
) -> list[dict[str, Any]]:
    """当板块无直接同花顺指数时，优先用本地已缓存 parquet 或新浪日线（耗时 <50ms）合成等权板块指数。"""
    sample = _prioritize_cached_codes(codes, limit=6)
    if not sample:
        return []
    futs = [_DETAIL_POOL.submit(_fetch_stock_kline_bars, c, count=count + 5) for c in sample]
    series_list: list[list[dict[str, Any]]] = []
    for fut in as_completed(futs):
        try:
            bars = fut.result()
            if len(bars) >= 10:
                series_list.append(bars)
        except Exception:
            continue

    if not series_list:
        return []

    by_date_rets: dict[str, list[tuple[float, float, float, float, float]]] = {}
    for bars in series_list:
        for i in range(1, len(bars)):
            prev_c = _clean(bars[i - 1].get("close"))
            cur = bars[i]
            c = _clean(cur.get("close"))
            if not prev_c or not c or prev_c <= 0:
                continue
            o = _clean(cur.get("open")) or c
            h = _clean(cur.get("high")) or max(o, c)
            lo = _clean(cur.get("low")) or min(o, c)
            amt = _clean(cur.get("amount")) or 0.0
            d = str(cur.get("date") or "")[:10]
            if not d:
                continue
            by_date_rets.setdefault(d, []).append(
                (o / prev_c - 1.0, h / prev_c - 1.0, lo / prev_c - 1.0, c / prev_c - 1.0, amt)
            )

    dates = sorted(by_date_rets.keys())[-count:]
    if not dates:
        return []
    level = 1000.0
    out: list[dict[str, Any]] = []
    for d in dates:
        items = by_date_rets[d]
        n = len(items)
        ro = sum(x[0] for x in items) / n
        rh = sum(x[1] for x in items) / n
        rlo = sum(x[2] for x in items) / n
        rc = sum(x[3] for x in items) / n
        amt_sum = sum(x[4] for x in items)
        open_px = round(level * (1.0 + ro), 2)
        close_px = round(level * (1.0 + rc), 2)
        high_px = round(max(open_px, close_px, level * (1.0 + rh)), 2)
        low_px = round(min(open_px, close_px, level * (1.0 + rlo)), 2)
        out.append(
            {
                "date": d,
                "open": open_px,
                "high": high_px,
                "low": low_px,
                "close": close_px,
                "amount": amt_sum if amt_sum > 0 else None,
            }
        )
        level = close_px
    return out


def _fill_segment_leaders(
    segments: list[dict[str, Any]],
    codes: list[str],
    name_map: dict[str, str],
    *,
    top_n: int = 3,
    codes_per_seg: int = 8,
) -> list[dict[str, Any]]:
    """优先使用本地缓存 parquet + 新浪高速日线并发计算各波段龙头（耗时 <50ms）。"""
    if not segments or not codes:
        return [{**seg, "leaders": []} for seg in segments]

    sample = _prioritize_cached_codes(codes, limit=max(codes_per_seg, 8))
    futs = {_DETAIL_POOL.submit(_fetch_stock_kline_bars, c, count=150): c for c in sample}
    bars_map: dict[str, list[dict[str, Any]]] = {}
    for fut in as_completed(futs):
        code = futs[fut]
        try:
            b = fut.result()
            if b:
                bars_map[code] = b
        except Exception:
            pass

    out: list[dict[str, Any]] = []
    for seg in segments:
        rows: list[dict[str, Any]] = []
        for code in sample:
            series = bars_map.get(code)
            ret = _return_from_bars(series, seg["start_date"], seg["end_date"]) if series else None
            if ret is None:
                continue
            rows.append(
                {
                    "code": code,
                    "name": name_map.get(code, code),
                    "return_pct": round(ret, 2),
                }
            )
        rows.sort(key=lambda x: float(x.get("return_pct") or 0), reverse=True)
        for rank, row in enumerate(rows[:top_n], start=1):
            row["rank"] = rank
        out.append({**seg, "leaders": rows[:top_n]})
    return out


def find_rally_segments(
    bars: list[dict[str, Any]],
    *,
    min_gain_pct: float = 3.0,
    min_days: int = 3,
    max_days: int = 20,
    max_segments: int = 8,
) -> list[dict[str, Any]]:
    """从概念指数 K 线识别上涨波段。"""
    if len(bars) < min_days + 1:
        return []

    segments: list[dict[str, Any]] = []
    i = 0
    n = len(bars)
    while i < n - min_days:
        start_close = _clean(bars[i].get("close"))
        if start_close is None:
            i += 1
            continue

        peak_idx = i
        peak_close = start_close
        j = i + 1
        while j < n and j - i < max_days:
            c = _clean(bars[j].get("close"))
            if c is None:
                break
            if c >= peak_close:
                peak_close = c
                peak_idx = j
            elif peak_idx > i and c < peak_close * 0.985:
                break
            j += 1

        if peak_idx > i and start_close > 0:
            gain = (peak_close / start_close - 1.0) * 100.0
            days = peak_idx - i + 1
            if gain >= min_gain_pct and days >= min_days:
                segments.append(
                    {
                        "start_date": bars[i]["date"],
                        "end_date": bars[peak_idx]["date"],
                        "start_idx": i,
                        "end_idx": peak_idx,
                        "gain_pct": round(gain, 2),
                        "days": days,
                    }
                )
                i = peak_idx + 1
                continue
        i += 1

    segments.sort(key=lambda x: float(x.get("gain_pct") or 0), reverse=True)
    deduped: list[dict[str, Any]] = []
    used: list[tuple[int, int]] = []
    for seg in segments:
        s, e = int(seg["start_idx"]), int(seg["end_idx"])
        if any(not (e < us or s > ue) for us, ue in used):
            continue
        used.append((s, e))
        deduped.append(seg)
        if len(deduped) >= max_segments:
            break
    deduped.sort(key=lambda x: x["start_date"])
    return deduped


def _doc_key(concept: str) -> str:
    return make_doc_key("sectors_detail", concept)


def _read_cached_detail(
    concept_name: str,
    *,
    force: bool,
    max_age_hours: float,
    require_segments: bool = False,
) -> dict[str, Any] | None:
    if force:
        return None
    cached = get_doc(_doc_key(concept_name), ttl_sec=300)
    if not isinstance(cached, dict):
        return None
    try:
        ts = str(cached.get("updated_at") or "")
        if not ts or not cached.get("kline"):
            return None
        if require_segments and not cached.get("segments_ready", bool(cached.get("segments"))):
            return None
        age = datetime.now() - datetime.fromisoformat(ts[:19])
        if age <= timedelta(hours=max_age_hours):
            return cached
    except Exception:
        return None
    return None


def read_cached_detail_only(concept_name: str) -> dict[str, Any] | None:
    """仅从内存/数据库读取已缓存的概念详情（0ms，不发起任何网络请求）。"""
    concept_name = str(concept_name or "").strip()
    if not concept_name:
        return None
    return _read_cached_detail(
        concept_name, force=False, max_age_hours=48.0, require_segments=False
    )


def _write_detail_cache(concept_name: str, resolved_name: str, payload: dict[str, Any]) -> None:
    set_doc(_doc_key(concept_name), payload, async_write=True)
    if resolved_name and resolved_name != concept_name:
        set_doc(_doc_key(resolved_name), payload, async_write=True)


def _fetch_members_fast(concept_name: str) -> list[dict[str, Any]]:
    """极速获取板块成分股预览（内存索引 0ms → 同花顺单页 / 东财）。"""
    names = _stock_name_map()
    codes = lookup_member_codes("概念", concept_name) or lookup_member_codes("行业", concept_name)
    if len(codes) >= 3:
        return [{"code": c, "name": names.get(c, c)} for c in codes[:80]]

    for kind in ("概念", "行业"):
        try:
            ths_df = fetch_ths_board_members(kind, concept_name, limit=50)
            if ths_df is not None and not ths_df.empty:
                col = "纯代码" if "纯代码" in ths_df.columns else "代码"
                fetched = [
                    {
                        "code": str(m.get(col) or "").zfill(6),
                        "name": str(m.get("名称") or ""),
                    }
                    for _, m in ths_df.iterrows()
                    if str(m.get(col) or "").strip()
                ]
                if fetched:
                    return fetched
        except Exception:
            continue

    try:
        from .rotation import em_available, em_concept_code_of, fetch_em_concept_members

        if em_available():
            for cand in candidate_concept_names(concept_name):
                bk = em_concept_code_of(cand)
                if bk:
                    em_mem = fetch_em_concept_members(bk, limit=80)
                    fetched = [
                        {
                            "code": str(m.get("纯代码") or m.get("代码") or "").zfill(6),
                            "name": str(m.get("名称") or ""),
                        }
                        for m in em_mem
                        if str(m.get("纯代码") or m.get("代码") or "").strip()
                    ]
                    if len(fetched) >= 3:
                        return fetched
    except Exception:
        pass

    return [{"code": c, "name": names.get(c, c)} for c in codes]


def build_concept_detail(
    concept_name: str,
    *,
    months: int = 6,
    force: bool = False,
    lite: bool = False,
) -> dict[str, Any]:
    """板块详情：近 N 月指数 K 线 + 波段龙头（使用常驻线程池，同花顺 CDN ~150ms 直出，绝不阻塞等待慢任务）。"""
    concept_name = str(concept_name or "").strip()
    if not concept_name:
        return {"error": "概念名为空"}

    fresh = _read_cached_detail(
        concept_name,
        force=force,
        max_age_hours=6.0,
        require_segments=not lite,
    )
    if fresh is not None:
        return {**fresh, "lite": lite and not fresh.get("segments_ready")}

    stale = _read_cached_detail(
        concept_name,
        force=force,
        max_age_hours=48.0,
        require_segments=not lite,
    )
    if stale is not None and not force:
        return {**stale, "stale": True, "lite": lite and not stale.get("segments_ready")}

    partial = None
    if not lite:
        partial = _read_cached_detail(
            concept_name, force=force, max_age_hours=6.0, require_segments=False
        )

    bar_count = max(60, int(months * 22))
    kline: list[dict[str, Any]] = list((partial or {}).get("kline") or [])
    source = str((partial or {}).get("source") or "同花顺板块")
    code = str((partial or {}).get("code") or "")
    resolved_name = str((partial or {}).get("resolved_concept") or (partial or {}).get("concept") or concept_name)
    member_rows: list[dict[str, Any]] = list((partial or {}).get("members_preview") or [])
    member_count = int((partial or {}).get("member_count") or len(member_rows))

    # 使用常驻线程池同时拉取同花顺 CDN K 线与内存成分股（不调用 shutdown(wait=True)）
    fut_ths = (
        _DETAIL_POOL.submit(fetch_ths_board_kline, concept_name, kind="概念", count=bar_count)
        if not kline
        else None
    )
    fut_mem = (
        _DETAIL_POOL.submit(_fetch_members_fast, concept_name)
        if len(member_rows) < 6
        else None
    )

    if fut_ths is not None:
        try:
            ths_bars, ths_code, ths_name = fut_ths.result(timeout=2.2)
            if ths_bars:
                kline = ths_bars
                code = ths_code or code
                resolved_name = ths_name or concept_name
                source = "同花顺板块"
        except Exception:
            pass

    if fut_mem is not None:
        try:
            fetched_mem = fut_mem.result(timeout=2.5)
            if fetched_mem:
                member_rows = fetched_mem
                member_count = max(member_count, len(fetched_mem))
        except Exception:
            pass

    # 若同花顺无此概念 clid（如「海上丝路」等别名或新概念），直接用成分股通过新浪高速日线合成（~120ms）
    if not kline and member_rows:
        synth = _synthesize_kline_from_members(
            [m["code"] for m in member_rows if m.get("code")], count=bar_count
        )
        if synth:
            kline = synth
            source = f"{source or '同花顺板块'}·指数合成"

    if not kline:
        tdx_meta = resolve_concept_by_name(concept_name)
        if tdx_meta and tdx_hq_available():
            try:
                tdx_bars = fetch_tdx_index_kline(tdx_meta["code"], count=bar_count)
                if tdx_bars:
                    kline = tdx_bars
                    code = str(tdx_meta["code"])
                    resolved_name = str(tdx_meta["name"])
                    source = "通达信板块"
            except Exception:
                pass

    if not kline:
        return {"error": f"无法拉取概念指数 K 线: {concept_name}"}

    codes = [m["code"] for m in member_rows if m.get("code")]
    global_names = _stock_name_map()
    name_map = {
        str(m["code"]): str(m.get("name") or global_names.get(str(m["code"])) or m["code"])
        for m in member_rows
        if m.get("code")
    }
    members = [
        {"code": m["code"], "name": name_map.get(m["code"], m["code"])}
        for m in member_rows[:50]
    ]
    if not member_count:
        member_count = len(codes)

    if lite:
        payload: dict[str, Any] = {
            "concept": concept_name,
            "resolved_concept": resolved_name or concept_name,
            "code": code,
            "source": source,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "months": months,
            "kline": kline,
            "segments": [],
            "segments_ready": False,
            "member_count": member_count,
            "members_preview": members,
            "lite": True,
        }
        existing = _read_cached_detail(
            concept_name, force=False, max_age_hours=48.0, require_segments=True
        )
        if existing is None:
            _write_detail_cache(concept_name, resolved_name, payload)
        return payload

    segments = find_rally_segments(kline, max_segments=5)
    rally_leaders = _fill_segment_leaders(
        segments, codes, name_map, top_n=3, codes_per_seg=8
    )

    payload = {
        "concept": concept_name,
        "resolved_concept": resolved_name or concept_name,
        "code": code,
        "source": source,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "months": months,
        "kline": kline,
        "segments": rally_leaders,
        "segments_ready": True,
        "member_count": member_count or len(codes),
        "members_preview": members,
        "lite": False,
    }
    _write_detail_cache(concept_name, resolved_name, payload)
    return payload
