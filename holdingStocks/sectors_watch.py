"""板块轮动实时数据 — 并入盯盘 WatchSnapshot（5s 刷新）。"""

from __future__ import annotations

import threading
import time
from typing import Any

from sectors.concept_leaders import build_concept_detail
from sectors.live import (
    concept_index_quote,
    fetch_concept_index_spot_live,
    leader_codes_from_detail,
    member_codes_for_concept,
    stock_quotes_by_codes,
)

_lock = threading.Lock()
_focus_concept: str | None = None
_focus_detail: dict[str, Any] | None = None
_focus_detail_ts: float = 0.0
_DETAIL_TTL_SEC = 6 * 3600.0
_last_spot: dict[str, dict[str, Any]] = {}
_last_spot_ts: float = 0.0


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
    global _focus_detail, _focus_detail_ts
    with _lock:
        concept = _focus_concept
        if not concept:
            return None
        now = time.time()
        if _focus_detail and _focus_detail.get("concept") == concept:
            if now - _focus_detail_ts < _DETAIL_TTL_SEC:
                return _focus_detail
        detail = build_concept_detail(concept, months=6, force=False)
        if detail.get("error"):
            return None
        _focus_detail = detail
        _focus_detail_ts = now
        return detail


def build_sectors_live_payload() -> dict[str, Any]:
    """构建 sectors 实时块（每轮盯盘 refresh 调用）。"""
    global _last_spot, _last_spot_ts
    try:
        spot = fetch_concept_index_spot_live()
        _last_spot = spot
        _last_spot_ts = time.time()
    except Exception as e:
        spot = _last_spot
        err = str(e)
    else:
        err = None

    focus = get_focus_concept()
    payload: dict[str, Any] = {
        "source": "通达信概念",
        "spotAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "conceptToday": spot,
        "focusConcept": focus,
        "error": err,
    }

    if focus:
        payload["conceptIndex"] = concept_index_quote(focus, spot)
        detail = _focus_detail_cached()
        codes = set(member_codes_for_concept(focus, limit=80))
        if detail:
            codes.update(leader_codes_from_detail(detail))
        try:
            quotes = stock_quotes_by_codes(sorted(codes))
        except Exception:
            quotes = {}
        payload["quotes"] = quotes
        if detail:
            payload["segmentCount"] = len(detail.get("segments") or [])
    return payload
