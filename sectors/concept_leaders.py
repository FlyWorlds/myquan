"""通达信概念波段龙头：近半年指数 K 线 + 上涨段成分股领涨统计。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .tdx import fetch_tdx_board_members, fetch_tdx_index_kline, resolve_concept_by_name

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


def _stock_return_pct(code: str, start: str, end: str) -> float | None:
    try:
        import akshare as ak

        df = ak.stock_zh_a_hist(
            symbol=str(code).zfill(6),
            period="daily",
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust="qfq",
        )
    except Exception:
        return None
    if df is None or df.empty:
        return None
    open_col = "开盘" if "开盘" in df.columns else None
    close_col = "收盘" if "收盘" in df.columns else None
    if not open_col or not close_col:
        return None
    first = _clean(df.iloc[0][open_col])
    last = _clean(df.iloc[-1][close_col])
    if not first or not last or first <= 0:
        return None
    return (last / first - 1.0) * 100.0


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


def _leaders_for_segment(
    codes: list[str],
    start_date: str,
    end_date: str,
    *,
    top_n: int = 3,
    max_workers: int = 12,
) -> list[dict[str, Any]]:
    names = _stock_name_map()
    results: list[dict[str, Any]] = []

    def _one(code: str) -> dict[str, Any] | None:
        ret = _stock_return_pct(code, start_date, end_date)
        if ret is None:
            return None
        return {
            "code": code,
            "name": names.get(code, code),
            "return_pct": round(ret, 2),
        }

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = [pool.submit(_one, c) for c in codes]
        for fut in as_completed(futs):
            row = fut.result()
            if row is not None:
                results.append(row)

    results.sort(key=lambda x: float(x.get("return_pct") or 0), reverse=True)
    for i, row in enumerate(results[:top_n], start=1):
        row["rank"] = i
    return results[:top_n]


def _cache_path(concept: str) -> Path:
    safe = concept.replace("/", "_").replace("\\", "_")
    return CACHE_DIR / f"concept_leaders_{safe}.json"


def build_concept_detail(
    concept_name: str,
    *,
    months: int = 6,
    force: bool = False,
) -> dict[str, Any]:
    """概念详情：近 N 月指数 K 线 + 波段龙头统计。"""
    concept_name = str(concept_name or "").strip()
    meta = resolve_concept_by_name(concept_name)
    if not meta:
        return {"error": f"未找到通达信概念: {concept_name}"}

    cache = _cache_path(concept_name)
    if cache.is_file() and not force:
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            ts = str(cached.get("updated_at") or "")
            if ts:
                age = datetime.now() - datetime.fromisoformat(ts)
                if age < timedelta(hours=6):
                    return cached
        except Exception:
            pass

    bar_count = max(60, int(months * 22))
    kline = fetch_tdx_index_kline(meta["code"], count=bar_count)
    if not kline:
        return {"error": f"无法拉取概念指数 K 线: {concept_name}"}

    members_df = fetch_tdx_board_members("概念", concept_name, with_quotes=False, limit=200)
    codes = []
    if members_df is not None and not members_df.empty:
        col = "纯代码" if "纯代码" in members_df.columns else "代码"
        codes = [str(c).zfill(6) for c in members_df[col].tolist() if str(c).strip()]

    segments = find_rally_segments(kline)
    rally_leaders: list[dict[str, Any]] = []
    for seg in segments:
        leaders = _leaders_for_segment(codes, seg["start_date"], seg["end_date"])
        rally_leaders.append({**seg, "leaders": leaders})

    names = _stock_name_map()
    members = [
        {"code": c, "name": names.get(c, c)}
        for c in codes[:50]
    ]

    payload: dict[str, Any] = {
        "concept": concept_name,
        "code": meta["code"],
        "source": "通达信概念",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "months": months,
        "kline": kline,
        "segments": rally_leaders,
        "member_count": len(codes),
        "members_preview": members,
    }

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload
