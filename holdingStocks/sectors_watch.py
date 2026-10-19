"""板块轮动实时数据 — 并入盯盘 WatchSnapshot（5s 刷新）。

缓存存入 MySQL `app_documents`（`sectors_live_fast`），不再读写本地 JSON 文件。
性能优化：`_focus_detail_cached` 仅做零网络缓存读取，绝不持有 `_lock` 执行耗时请求，消除与详情页 `setFocus` / `load` 的锁竞争。
"""

from __future__ import annotations

import threading
import time
from typing import Any

from sectors.concept_leaders import read_cached_detail_only
from sectors.live import (
    concept_index_quote,
    fetch_concept_index_spot_live,
    leader_codes_from_detail,
    live_source,
    member_codes_for_concept,
    stock_quotes_by_codes,
)
from sectors.metrics import (
    all_member_codes,
    build_member_stats_map,
    enrich_concept_row,
    fetch_em_concept_main_flow,
    fetch_member_quotes_sina,
)
from sectors.sina_boards import fetch_sina_concept_spot_fast
from sectors.store import get_doc, set_doc

_lock = threading.Lock()
_focus_concept: str | None = None
_focus_detail: dict[str, Any] | None = None
_focus_detail_ts: float = 0.0
_DETAIL_TTL_SEC = 6 * 3600.0
_last_spot: dict[str, dict[str, Any]] = {}
_last_spot_ts: float = 0.0
_last_member_stats: dict[str, dict[str, Any]] = {}
_last_member_stats_ts: float = 0.0
_last_main_flow: dict[str, float] = {}
_last_main_flow_ts: float = 0.0
_last_payload: dict[str, Any] = {}
_last_deep_attempt_ts: float = 0.0
_last_member_stats_attempt_ts: float = 0.0
_last_fast_cache_load_ts: float = 0.0
_MEMBER_STATS_INTERVAL = 120.0
_MAIN_FLOW_INTERVAL = 60.0
_DEEP_SPOT_INTERVAL = 30.0
_FAST_DOC_KEY = "sectors_live_fast"
_tick = 0


def set_focus_concept(name: str | None) -> None:
    global _focus_concept, _focus_detail, _focus_detail_ts
    with _lock:
        cleaned = str(name or "").strip() or None
        if cleaned == _focus_concept:
            return
        _focus_concept = cleaned
        _focus_detail = None
        _focus_detail_ts = 0.0


def get_focus_concept() -> str | None:
    with _lock:
        return _focus_concept


def _focus_detail_cached() -> dict[str, Any] | None:
    """仅读取已就绪的内存/数据库详情缓存，不阻塞实时线程或锁。"""
    global _focus_detail, _focus_detail_ts
    with _lock:
        concept = _focus_concept
        if not concept:
            return None
        now = time.time()
        if _focus_detail and _focus_detail.get("concept") == concept:
            if now - _focus_detail_ts < _DETAIL_TTL_SEC:
                return _focus_detail

    detail = read_cached_detail_only(concept)
    if not detail or detail.get("error"):
        return None
    with _lock:
        if _focus_concept == concept:
            _focus_detail = detail
            _focus_detail_ts = time.time()
    return detail


def peek_sectors_live_payload() -> dict[str, Any]:
    """最近一次板块实时块（优先内存，其次读取数据库缓存）。"""
    cached = _read_fast_cache()
    if cached:
        return cached
    with _lock:
        return dict(_last_payload) if _last_payload else {}


def _read_fast_cache() -> dict[str, Any]:
    global _last_payload, _last_fast_cache_load_ts
    now = time.time()
    with _lock:
        if _last_payload:
            return dict(_last_payload)
        if now - _last_fast_cache_load_ts < 2.0:
            return {}
        _last_fast_cache_load_ts = now
    payload = get_doc(_FAST_DOC_KEY, ttl_sec=60.0)
    if not isinstance(payload, dict) or not payload.get("conceptToday"):
        return {}
    cached = dict(payload)
    cached["cache"] = True
    cached["source"] = f"{cached.get('source') or '同花顺热点轮动'}·数据库缓存"
    with _lock:
        if not _last_payload:
            _last_payload = cached
    return cached


def _write_fast_cache(payload: dict[str, Any]) -> None:
    if not payload.get("conceptToday"):
        return
    set_doc(_FAST_DOC_KEY, payload, async_write=True)


def _fast_spot() -> tuple[dict[str, dict[str, Any]], str | None]:
    try:
        return fetch_sina_concept_spot_fast(timeout=3.0), None
    except Exception as e:
        return {}, str(e)


def build_sectors_live_payload() -> dict[str, Any]:
    """构建 sectors 实时块（板块线程 / CLI 调用）。"""
    global _last_spot, _last_spot_ts, _last_member_stats, _last_member_stats_ts
    global _last_main_flow, _last_main_flow_ts, _last_payload, _tick
    global _last_deep_attempt_ts, _last_member_stats_attempt_ts
    _tick += 1
    err: str | None = None
    now = time.time()

    fast_raw, fast_err = _fast_spot()
    spot_raw = dict(fast_raw or _last_spot)
    source = "新浪板块摘要" if fast_raw else live_source()
    if fast_err:
        err = fast_err

    deep_due = False
    if not fast_raw:
        deep_due = True
    elif not _last_spot and _tick <= 1:
        _last_deep_attempt_ts = now
    elif now - _last_deep_attempt_ts >= _DEEP_SPOT_INTERVAL:
        deep_due = True

    if deep_due:
        _last_deep_attempt_ts = now
        try:
            deep = fetch_concept_index_spot_live()
            if deep:
                _last_spot = deep
                _last_spot_ts = time.time()
                merged = dict(fast_raw)
                merged.update(deep)
                spot_raw = merged
                source = live_source()
        except Exception as e:
            if not err:
                err = str(e)
    elif _last_spot:
        merged = dict(fast_raw)
        merged.update(_last_spot)
        spot_raw = merged
        source = live_source()

    if fast_raw and not _last_member_stats and _last_member_stats_attempt_ts <= 0:
        _last_member_stats_attempt_ts = now
        member_due = False
    else:
        member_due = (
            (now - _last_member_stats_ts >= _MEMBER_STATS_INTERVAL or not _last_member_stats)
            and now - _last_member_stats_attempt_ts >= _MEMBER_STATS_INTERVAL
        )
    if member_due:
        _last_member_stats_attempt_ts = now
        try:
            quotes = fetch_member_quotes_sina(all_member_codes())
            _last_member_stats = build_member_stats_map(quotes)
            _last_member_stats_ts = now
        except Exception as e:
            if not err:
                err = str(e)
    if now - _last_main_flow_ts >= _MAIN_FLOW_INTERVAL or not _last_main_flow:
        try:
            _last_main_flow = fetch_em_concept_main_flow()
            _last_main_flow_ts = now
        except Exception:
            pass

    spot: dict[str, dict[str, Any]] = {}
    for name, base in spot_raw.items():
        spot[name] = enrich_concept_row(
            name,
            base,
            member_stats=_last_member_stats,
            main_flow=_last_main_flow,
        )

    focus = get_focus_concept()
    payload: dict[str, Any] = {
        "source": source,
        "spotAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "conceptToday": spot,
        "focusConcept": focus,
        "error": err,
        "fastSource": "新浪板块摘要" if fast_raw else None,
        "deepSource": live_source() if _last_spot_ts else None,
        "memberStatsAt": time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(_last_member_stats_ts)
        )
        if _last_member_stats_ts
        else None,
    }

    if focus:
        payload["conceptIndex"] = concept_index_quote(focus, spot)
        detail = _focus_detail_cached()
        codes: set[str] = set()
        if detail:
            codes.update(leader_codes_from_detail(detail))
        else:
            from sectors.tdx import lookup_member_codes

            codes.update(lookup_member_codes("概念", focus)[:50])
        try:
            quotes = stock_quotes_by_codes(sorted(codes)) if codes else {}
        except Exception:
            quotes = {}
        payload["quotes"] = quotes
        if detail:
            payload["segmentCount"] = len(detail.get("segments") or [])
    with _lock:
        _last_payload = payload
    _write_fast_cache(payload)
    return payload
