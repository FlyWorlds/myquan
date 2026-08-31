"""板块轮动 HTTP API 数据层（供 holdingStocks watch 服务调用）。"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .concept_leaders import build_concept_detail
from .leader_score import get_concept_scored_leaders
from .tdx import tdx_availability, tdx_hq_available
from .tdx_rotation import (
    build_em_concept_rotation_payload,
    build_tdx_concept_rotation_payload,
)

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"
_ROTATION_CACHE = CACHE_DIR / "tdx_rotation_api.json"

_lock = threading.Lock()
_rotation_mem: dict[str, Any] = {"payload": None, "ts": 0.0}
_ROTATION_TTL_SEC = 3600.0


def _load_rotation_disk() -> dict[str, Any] | None:
    if not _ROTATION_CACHE.is_file():
        return None
    try:
        return json.loads(_ROTATION_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_rotation_disk(payload: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _ROTATION_CACHE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


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


def get_rotation_payload(*, days: int = 20, top_n: int = 10, refresh: bool = False) -> dict[str, Any]:
    """通达信概念轮动 payload（内存 + 磁盘缓存）；空结果不缓存，行情失败回退东财。"""
    now = time.time()
    with _lock:
        mem = _rotation_mem.get("payload")
        if (
            not refresh
            and _rotation_has_data(mem)
            and now - float(_rotation_mem.get("ts") or 0) < _ROTATION_TTL_SEC
        ):
            return mem

        if not refresh:
            disk = _load_rotation_disk()
            if _rotation_has_data(disk):
                _rotation_mem["payload"] = disk
                _rotation_mem["ts"] = now
                return disk

    payload: dict[str, Any] | None = None
    if tdx_hq_available():
        try:
            payload = build_tdx_concept_rotation_payload(
                days=days, top_n=top_n, with_members=True
            )
        except Exception:
            payload = None
    if not _rotation_has_data(payload):
        payload = build_em_concept_rotation_payload(days=days, top_n=top_n)
    if not _rotation_has_data(payload):
        raise RuntimeError("板块轮动无数据：通达信与东财均失败")
    with _lock:
        _rotation_mem["payload"] = payload
        _rotation_mem["ts"] = time.time()
    _save_rotation_disk(payload)
    return payload


def get_concept_detail(concept_name: str, *, months: int = 6, refresh: bool = False) -> dict[str, Any]:
    name = unquote(str(concept_name or "").strip())
    return build_concept_detail(name, months=months, force=refresh)


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
    info = tdx_availability()
    info["rotation_cached"] = _ROTATION_CACHE.is_file()
    return info
