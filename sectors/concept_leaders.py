"""通达信概念波段龙头：近半年指数 K 线 + 上涨段成分股领涨统计。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .tdx import (
    fetch_tdx_board_members,
    fetch_tdx_index_kline,
    fetch_tdx_stock_klines,
    resolve_concept_by_name,
    tdx_hq_available,
)

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"


def _clean(v: Any) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        x = float(v)
        return None if pd.isna(x) else x
    except (TypeError, ValueError):
        return None


_NAME_MAP: dict[str, str] | None = None
_RET_CACHE: dict[tuple[str, str, str], float | None] = {}


def _stock_name_map() -> dict[str, str]:
    global _NAME_MAP
    if _NAME_MAP is not None:
        return _NAME_MAP
    try:
        import akshare as ak

        df = ak.stock_info_a_code_name()
        if df is None or df.empty:
            _NAME_MAP = {}
            return _NAME_MAP
        code_col = "code" if "code" in df.columns else df.columns[0]
        name_col = "name" if "name" in df.columns else df.columns[1]
        _NAME_MAP = {
            str(c).zfill(6): str(n)
            for c, n in zip(df[code_col], df[name_col], strict=False)
        }
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


def _stock_return_pct(code: str, start: str, end: str) -> float | None:
    code = str(code).zfill(6)
    key = (code, str(start)[:10], str(end)[:10])
    if key in _RET_CACHE:
        return _RET_CACHE[key]
    ret: float | None = None
    # 通达信优先（东财/akshare 常被墙导致详情空白）
    if tdx_hq_available():
        try:
            series = fetch_tdx_stock_klines([code], count=180).get(code) or []
            ret = _return_from_bars(series, start, end)
        except Exception:
            ret = None
    if ret is None:
        try:
            from .rotation import _http

            mkt = 1 if code.startswith("6") else 0
            sess = _http()
            r = sess.get(
                "https://push2his.eastmoney.com/api/qt/stock/kline/get",
                params={
                    "secid": f"{mkt}.{code}",
                    "fields1": "f1,f2,f3,f4,f5,f6",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57",
                    "klt": 101,
                    "fqt": 1,
                    "beg": str(start).replace("-", "")[:8],
                    "end": str(end).replace("-", "")[:8],
                    "lmt": 800,
                },
                timeout=12,
            )
            r.raise_for_status()
            klines = ((r.json() or {}).get("data") or {}).get("klines") or []
            if len(klines) >= 2:
                first = str(klines[0]).split(",")
                last = str(klines[-1]).split(",")
                o = _clean(first[1]) if len(first) > 1 else None
                c = _clean(last[2]) if len(last) > 2 else None
                if o and c and o > 0:
                    ret = (c / o - 1.0) * 100.0
        except Exception:
            pass
    if ret is None:
        try:
            import akshare as ak

            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start.replace("-", ""),
                end_date=end.replace("-", ""),
                adjust="qfq",
            )
            if df is not None and not df.empty:
                open_col = "开盘" if "开盘" in df.columns else None
                close_col = "收盘" if "收盘" in df.columns else None
                if open_col and close_col:
                    first = _clean(df.iloc[0][open_col])
                    last = _clean(df.iloc[-1][close_col])
                    if first and last and first > 0:
                        ret = (last / first - 1.0) * 100.0
        except Exception:
            ret = None
    _RET_CACHE[key] = ret
    return ret


def _fill_segment_leaders(
    segments: list[dict[str, Any]],
    codes: list[str],
    name_map: dict[str, str],
    *,
    top_n: int = 3,
    codes_per_seg: int = 12,
) -> list[dict[str, Any]]:
    """一次批量拉通达信个股 K，再算各波段龙头（避免串行东财 HTTP）。"""
    if not segments or not codes:
        return [{**seg, "leaders": []} for seg in segments]

    sample = [str(c).zfill(6) for c in codes[: max(codes_per_seg, 40)]]
    bars_map: dict[str, list[dict[str, Any]]] = {}
    if tdx_hq_available():
        try:
            bars_map = fetch_tdx_stock_klines(sample, count=180)
        except Exception:
            bars_map = {}

    out: list[dict[str, Any]] = []
    for seg in segments:
        rows: list[dict[str, Any]] = []
        for code in sample:
            if code in bars_map:
                ret = _return_from_bars(bars_map[code], seg["start_date"], seg["end_date"])
            else:
                ret = _stock_return_pct(code, seg["start_date"], seg["end_date"])
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
    """从概念指数 K 线识别上涨波段（近似通达信龙头标注区间）。"""
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


def _cache_path(concept: str) -> Path:
    safe = concept.replace("/", "_").replace("\\", "_")
    return CACHE_DIR / f"concept_leaders_{safe}.json"


def _read_cached_detail(
    concept_name: str,
    *,
    force: bool,
    max_age_hours: float,
    require_segments: bool = False,
) -> dict[str, Any] | None:
    cache = _cache_path(concept_name)
    if force or not cache.is_file():
        return None
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        ts = str(cached.get("updated_at") or "")
        if not ts or not cached.get("kline"):
            return None
        if require_segments and not cached.get("segments_ready", bool(cached.get("segments"))):
            return None
        age = datetime.now() - datetime.fromisoformat(ts)
        if age <= timedelta(hours=max_age_hours):
            return cached
    except Exception:
        return None
    return None


def _write_detail_cache(concept_name: str, resolved_name: str, payload: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False)
    _cache_path(concept_name).write_text(text, encoding="utf-8")
    if resolved_name and resolved_name != concept_name:
        _cache_path(resolved_name).write_text(text, encoding="utf-8")


def build_concept_detail(
    concept_name: str,
    *,
    months: int = 6,
    force: bool = False,
    lite: bool = False,
) -> dict[str, Any]:
    """概念详情：近 N 月指数 K 线 + 波段龙头。通达信优先。

    lite=True：只返回 K 线/成分预览（秒开）；完整波段龙头需再请求 lite=False。
    """
    concept_name = str(concept_name or "").strip()
    if not concept_name:
        return {"error": "概念名为空"}

    # 新鲜完整缓存 / lite 可用缓存
    fresh = _read_cached_detail(
        concept_name,
        force=force,
        max_age_hours=6.0,
        require_segments=not lite,
    )
    if fresh is not None:
        out = {**fresh, "lite": lite and not fresh.get("segments_ready")}
        return out

    # 过期但可用：非 force 时先返回，避免详情页卡住
    stale = _read_cached_detail(
        concept_name,
        force=force,
        max_age_hours=48.0,
        require_segments=not lite,
    )
    if stale is not None and not force:
        return {**stale, "stale": True, "lite": lite and not stale.get("segments_ready")}

    # 完整请求可复用同名 lite 缓存里的 K 线（避免二次拉指数）
    partial = None
    if not lite:
        partial = _read_cached_detail(
            concept_name, force=force, max_age_hours=6.0, require_segments=False
        )

    bar_count = max(60, int(months * 22))
    tdx_meta = resolve_concept_by_name(concept_name)
    kline: list[dict[str, Any]] = list((partial or {}).get("kline") or [])
    source = str((partial or {}).get("source") or "通达信概念")
    code = str((partial or {}).get("code") or (tdx_meta or {}).get("code") or "")
    resolved_name = str(
        (partial or {}).get("concept") or (tdx_meta or {}).get("name") or concept_name
    )
    member_rows: list[dict[str, Any]] = list((partial or {}).get("members_preview") or [])
    member_count = int((partial or {}).get("member_count") or len(member_rows))

    if not kline and tdx_meta:
        try:
            if tdx_hq_available():
                kline = fetch_tdx_index_kline(tdx_meta["code"], count=bar_count)
                code = str(tdx_meta.get("code") or code)
                resolved_name = str(tdx_meta.get("name") or resolved_name)
                source = "通达信概念"
        except Exception:
            kline = []

    if len(member_rows) < 8 and (tdx_meta or resolved_name):
        try:
            members_df = fetch_tdx_board_members(
                "概念", resolved_name, with_quotes=False, limit=200
            )
            if members_df is not None and not members_df.empty:
                col = "纯代码" if "纯代码" in members_df.columns else "代码"
                fetched: list[dict[str, Any]] = []
                for _, m in members_df.iterrows():
                    c = str(m.get(col) or "").zfill(6)
                    if c.isdigit():
                        fetched.append({"code": c, "name": str(m.get("名称") or c)})
                if fetched:
                    member_rows = fetched
                    member_count = len(fetched)
                    if not source.startswith("东财"):
                        source = "通达信概念"
        except Exception:
            pass

    if not kline or len(member_rows) < 8:
        try:
            from .rotation import (
                em_concept_code_of,
                fetch_em_concept_kline,
                fetch_em_concept_members,
            )

            bk = em_concept_code_of(concept_name) or em_concept_code_of(resolved_name)
        except Exception:
            bk = None
        if bk:
            if not kline:
                try:
                    kline = fetch_em_concept_kline(bk, count=bar_count)
                    if kline:
                        source = "东财概念"
                        code = bk
                except Exception:
                    pass
            if len(member_rows) < 8:
                try:
                    em_mem = fetch_em_concept_members(bk, limit=200)
                    fetched = [
                        {
                            "code": str(m.get("纯代码") or m.get("代码") or "").zfill(6),
                            "name": str(m.get("名称") or ""),
                        }
                        for m in em_mem
                        if str(m.get("纯代码") or m.get("代码") or "").strip()
                    ]
                    if fetched:
                        member_rows = fetched
                        member_count = len(fetched)
                        if source != "通达信概念":
                            source = "东财概念"
                            code = code or bk
                except Exception:
                    pass

    if not kline:
        return {"error": f"无法拉取概念指数 K 线: {concept_name}"}

    codes = [m["code"] for m in member_rows if m.get("code")]
    name_map = {
        str(m["code"]): str(m.get("name") or m["code"])
        for m in member_rows
        if m.get("code")
    }
    members = [
        {"code": m["code"], "name": m.get("name") or m["code"]}
        for m in member_rows[:50]
    ]
    if not member_count:
        member_count = len(codes)

    if lite:
        payload: dict[str, Any] = {
            "concept": resolved_name or concept_name,
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
        # 不覆盖已有完整缓存
        existing = _read_cached_detail(
            concept_name, force=False, max_age_hours=48.0, require_segments=True
        )
        if existing is None:
            _write_detail_cache(concept_name, resolved_name, payload)
        return payload

    # 完整：波段数/成分抽样收紧，并发拉龙头
    segments = find_rally_segments(kline, max_segments=5)
    rally_leaders = _fill_segment_leaders(
        segments, codes, name_map, top_n=3, codes_per_seg=8
    )

    payload = {
        "concept": resolved_name or concept_name,
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
