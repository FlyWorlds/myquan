"""板块轮动 HTTP API 数据层（供 holdingStocks watch 服务调用）。"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .concept_leaders import build_concept_detail
from .tdx import tdx_availability
from .tdx_rotation import build_tdx_concept_rotation_payload

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


def get_rotation_payload(*, days: int = 20, top_n: int = 10, refresh: bool = False) -> dict[str, Any]:
    """通达信概念轮动 payload（内存 + 磁盘缓存）。"""
    now = time.time()
    with _lock:
        if (
            not refresh
            and _rotation_mem.get("payload")
            and now - float(_rotation_mem.get("ts") or 0) < _ROTATION_TTL_SEC
        ):
            return _rotation_mem["payload"]

        if not refresh:
            disk = _load_rotation_disk()
            if disk and disk.get("kinds"):
                _rotation_mem["payload"] = disk
                _rotation_mem["ts"] = now
                return disk

    payload = build_tdx_concept_rotation_payload(days=days, top_n=top_n, with_members=True)
    with _lock:
        _rotation_mem["payload"] = payload
        _rotation_mem["ts"] = time.time()
    _save_rotation_disk(payload)
    return payload


def get_concept_detail(concept_name: str, *, months: int = 6, refresh: bool = False) -> dict[str, Any]:
    name = unquote(str(concept_name or "").strip())
    return build_concept_detail(name, months=months, force=refresh)


def get_status() -> dict[str, Any]:
    info = tdx_availability()
    info["rotation_cached"] = _ROTATION_CACHE.is_file()
    return info
