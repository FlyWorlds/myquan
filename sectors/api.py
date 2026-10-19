"""板块轮动 HTTP API 数据层（供 holdingStocks watch 服务调用）。

数据源优先级：同花顺 → 东方财富 → 新浪 → 通达信。
持久化：全部写入 MySQL `app_documents`（`sectors/store.py`），不再读写本地 JSON 文件。
性能优化：支持 Stale-While-Revalidate（有数据库缓存时 <20ms 秒回，后台异步刷新同花顺 20 日全量轮动）。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any
from urllib.parse import unquote

from .concept_leaders import build_concept_detail
from .leader_score import get_concept_scored_leaders
from .live import fetch_concept_member_rows
from .rotation_cache import (
    date_columns,
    ensure_today_column,
    payload_has_today_column,
    payload_session_fresh,
    resolve_rotation_payload,
    today_ymd,
    trading_columns_only,
)
from .store import get_doc, set_doc
from .tdx import tdx_availability, tdx_hq_available
from .tdx_rotation import (
    build_em_concept_rotation_payload,
    build_sina_rotation_payload,
    build_tdx_concept_rotation_payload,
    build_ths_rotation_payload,
    compute_hot_periods_and_board_stats,
)
from .ths import ths_availability

_ROTATION_DOC_KEY = "sectors_rotation_api"

_lock = threading.Lock()
_rotation_mem: dict[str, Any] = {"payload": None, "ts": 0.0}
_bg_refreshing = False
_ROTATION_TTL_SEC = 1800.0
_STALE_MAX_SEC = 86400.0 * 3


def _ensure_hot_periods(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """确保缓存中的每个板块类别都包含 1/3/5/10 日热门卡片和上榜次数统计。"""
    if not payload or not isinstance(payload, dict):
        return payload
    kinds = payload.get("kinds")
    if not isinstance(kinds, dict):
        return payload
    changed = False
    out_kinds: dict[str, Any] = {}
    top_n = int(payload.get("top_n") or 10)
    for kname, block in kinds.items():
        if not isinstance(block, dict):
            out_kinds[kname] = block
            continue
        if block.get("hot_periods") and block.get("board_stats"):
            out_kinds[kname] = block
            continue
        dates = block.get("dates") or []
        chg_tops = ((block.get("by_metric") or {}).get("涨幅") or {}).get("top") or []
        flow_tops = ((block.get("by_metric") or {}).get("主力净额") or {}).get("top") or []
        amt_tops = ((block.get("by_metric") or {}).get("成交额") or {}).get("top") or []
        snaps_desc: list[dict[str, Any]] = []
        for idx, d in enumerate(dates):
            col = chg_tops[idx] if idx < len(chg_tops) else []
            fcol = {
                str(c.get("name") or ""): c.get("value")
                for c in (flow_tops[idx] if idx < len(flow_tops) else [])
                if isinstance(c, dict)
            }
            acol = {
                str(c.get("name") or ""): c.get("value")
                for c in (amt_tops[idx] if idx < len(amt_tops) else [])
                if isinstance(c, dict)
            }
            boards_rows = []
            for cell in col:
                if not isinstance(cell, dict):
                    continue
                nm = str(cell.get("name") or "").strip()
                if not nm:
                    continue
                boards_rows.append(
                    {
                        "板块": nm,
                        "label": str(cell.get("label") or ""),
                        "涨跌幅": cell.get("value"),
                        "主力净额": cell.get("net_inflow") if cell.get("net_inflow") is not None else fcol.get(nm),
                        "资金": cell.get("amount") if cell.get("amount") is not None else acol.get(nm),
                        "领涨名称": str(cell.get("leader_name") or ""),
                        "领涨涨幅": cell.get("leader_chg"),
                    }
                )
            snaps_desc.append({"date": d, "kind": kname, "boards": boards_rows})
        today_rows = snaps_desc[0]["boards"] if snaps_desc else []
        hot_periods, board_stats = compute_hot_periods_and_board_stats(
            snaps_desc, today_rows, top_n=top_n
        )
        new_block = dict(block)
        new_block["hot_periods"] = hot_periods
        new_block["board_stats"] = board_stats
        out_kinds[kname] = new_block
        changed = True
    if not changed:
        return payload
    out = dict(payload)
    out["kinds"] = out_kinds
    return out


def _load_rotation_db() -> dict[str, Any] | None:
    doc = get_doc(_ROTATION_DOC_KEY, ttl_sec=60)
    if not isinstance(doc, dict):
        return None
    try:
        cleaned = trading_columns_only(doc)
        return _ensure_hot_periods(cleaned)
    except Exception:
        return None


def _save_rotation_db(payload: dict[str, Any]) -> None:
    set_doc(_ROTATION_DOC_KEY, payload, async_write=True)


def _rotation_has_data(payload: dict[str, Any] | None) -> bool:
    if not payload or not isinstance(payload, dict):
        return False
    kind = (payload.get("kinds") or {}).get("概念") or {}
    if int(kind.get("board_count") or 0) > 0:
        return True
    by = kind.get("by_metric") or {}
    for block in by.values():
        if not isinstance(block, dict):
            continue
        for col in block.get("top") or []:
            if col:
                return True
    return False


def _payload_age_sec(payload: dict[str, Any] | None) -> float:
    if not payload:
        return 1e9
    raw = str(payload.get("updated_at") or "")
    if not raw:
        return 1e9
    try:
        ts = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        return max(0.0, (datetime.now() - ts).total_seconds())
    except ValueError:
        return 1e9


def _fetch_fresh_rotation(
    *,
    days: int,
    top_n: int,
    db_cached: dict[str, Any] | None,
    today: str,
) -> dict[str, Any] | None:
    fresh: dict[str, Any] | None = None

    # 1. 优先同花顺热点轮动（概念 + 行业）
    try:
        ths = build_ths_rotation_payload(days=days, top_n=top_n, with_members=False)
        if _rotation_has_data(ths):
            fresh = ths
    except Exception:
        fresh = None

    # 2. 回退东方财富
    if not payload_has_today_column(fresh, today=today):
        try:
            em = build_em_concept_rotation_payload(days=days, top_n=top_n)
            if _rotation_has_data(em):
                fresh = resolve_rotation_payload(
                    fresh=em, disk=fresh or db_cached, today=today, days=days
                )
        except Exception:
            pass

    # 3. 回退新浪板块
    if not payload_has_today_column(fresh, today=today):
        try:
            sina = build_sina_rotation_payload(days=days, top_n=top_n)
            if _rotation_has_data(sina):
                fresh = resolve_rotation_payload(
                    fresh=sina, disk=fresh or db_cached, today=today, days=days
                )
        except Exception:
            pass

    # 4. 回退通达信
    if not payload_has_today_column(fresh, today=today) and tdx_hq_available():
        try:
            tdx = build_tdx_concept_rotation_payload(
                days=days, top_n=top_n, with_members=False
            )
            if _rotation_has_data(tdx):
                fresh = tdx
        except Exception:
            pass

    payload = resolve_rotation_payload(
        fresh=fresh, disk=db_cached, today=today, days=days
    )
    if not _rotation_has_data(payload):
        return None
    payload = _ensure_hot_periods(trading_columns_only(payload))
    if payload:
        with _lock:
            _rotation_mem["payload"] = payload
            _rotation_mem["ts"] = time.time()
        if payload_has_today_column(payload, today=today) and len(
            date_columns(payload)
        ) >= len(date_columns(db_cached)):
            _save_rotation_db(payload)
    return payload


def _trigger_bg_refresh(days: int, top_n: int, db_cached: dict[str, Any] | None) -> None:
    global _bg_refreshing
    with _lock:
        if _bg_refreshing:
            return
        _bg_refreshing = True

    def _worker() -> None:
        global _bg_refreshing
        try:
            _fetch_fresh_rotation(
                days=days, top_n=top_n, db_cached=db_cached, today=today_ymd()
            )
        except Exception:
            pass
        finally:
            with _lock:
                _bg_refreshing = False

    threading.Thread(target=_worker, name="sectors-rotation-swr", daemon=True).start()


def get_rotation_payload(*, days: int = 20, top_n: int = 10, refresh: bool = False) -> dict[str, Any]:
    """板块热门轮动 payload（内存 + MySQL 数据库存储 + SWR 异步刷新）。"""
    today = today_ymd()
    now = time.time()
    with _lock:
        mem = _rotation_mem.get("payload")
        if (
            not refresh
            and _rotation_has_data(mem)
            and payload_session_fresh(mem, today=today)
            and now - float(_rotation_mem.get("ts") or 0) < _ROTATION_TTL_SEC
        ):
            return trading_columns_only(mem)  # type: ignore[return-value]

    db_cached = _load_rotation_db()
    if not refresh and _rotation_has_data(db_cached):
        is_fresh_ths = (
            payload_session_fresh(db_cached, today=today)
            and _payload_age_sec(db_cached) < _ROTATION_TTL_SEC
            and "同花顺" in str((db_cached or {}).get("source") or "")
        )
        with _lock:
            _rotation_mem["payload"] = db_cached
            _rotation_mem["ts"] = now if is_fresh_ths else 0.0
        if is_fresh_ths:
            return db_cached  # type: ignore[return-value]
        # Stale-While-Revalidate：立即返回数据库已有缓存（保证首屏 <20ms 秒开），后台异步刷新同花顺
        _trigger_bg_refresh(days, top_n, db_cached)
        ensured = ensure_today_column(db_cached, today=today, days=days)
        return _ensure_hot_periods(trading_columns_only(ensured)) or db_cached  # type: ignore[return-value]

    payload = _fetch_fresh_rotation(
        days=days, top_n=top_n, db_cached=db_cached, today=today
    )
    if not _rotation_has_data(payload):
        if _rotation_has_data(db_cached) and _payload_age_sec(db_cached) < _STALE_MAX_SEC:
            return db_cached  # type: ignore[return-value]
        raise RuntimeError("板块轮动无数据：同花顺、东财、新浪与通达信均失败")
    assert payload is not None
    return payload


def get_concept_members(concept_name: str, *, limit: int = 80, kind: str = "概念") -> dict[str, Any]:
    name = unquote(str(concept_name or "").strip())
    return fetch_concept_member_rows(name, limit=limit, kind=kind)


def get_concept_detail(
    concept_name: str,
    *,
    months: int = 6,
    refresh: bool = False,
    lite: bool = False,
) -> dict[str, Any]:
    name = unquote(str(concept_name or "").strip())
    return build_concept_detail(name, months=months, force=refresh, lite=lite)


def get_concept_leader_scores(
    concept_name: str,
    *,
    start: str = "2025-01-01",
    refresh: bool = False,
    top_n: int = 5,
) -> dict[str, Any]:
    name = unquote(str(concept_name or "").strip())
    return get_concept_scored_leaders(name, start=start, force=refresh, top_n=top_n)


def get_status() -> dict[str, Any]:
    info = ths_availability()
    tdx_info = tdx_availability()
    info["tdx"] = tdx_info
    info["prefer"] = "同花顺"
    info["storage"] = "database"
    info["rotation_cached"] = bool(get_doc(_ROTATION_DOC_KEY, ttl_sec=60))
    return info
