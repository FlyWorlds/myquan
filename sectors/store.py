"""板块轮动数据库存储层（基于 MySQL app_documents，替代本地 JSON 缓存文件）。

生产环境（HOLDINGS_STORAGE=database，默认）通过 Java 后端 `/api/documents/{key}` 读写 MySQL；
进程内维护轻量内存缓存减少重复 HTTP 请求；离线测试模式（HOLDINGS_STORAGE=local_json）仅驻留内存，
不再在 sectors/cache、sectors/snapshots 或 data_cache 下生成任何本地 .json 文件。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"
SNAP_DIR = ROOT / "snapshots"
DATA_CACHE_DIR = ROOT.parent / "data_cache"

_HOLDING_DIR = ROOT.parent / "holdingStocks"
if str(_HOLDING_DIR) not in sys.path:
    sys.path.insert(0, str(_HOLDING_DIR))

_LOCK = threading.RLock()
_MEM_CACHE: dict[str, tuple[float, Any]] = {}
_MIGRATED = False


def _db_enabled() -> bool:
    mode = os.environ.get("HOLDINGS_STORAGE", "database")
    return mode == "database"


def make_doc_key(prefix: str, suffix: str = "") -> str:
    """生成符合 Java DocumentService `[a-z][a-z0-9_]{0,63}` 规范的 doc_key。"""
    clean_prefix = "".join(ch if ch.isalnum() else "_" for ch in prefix.lower()).strip("_")
    if not clean_prefix or not clean_prefix[0].isalpha():
        clean_prefix = "s_" + clean_prefix
    if not suffix:
        return clean_prefix[:64]
    digest = hashlib.md5(str(suffix).encode("utf-8")).hexdigest()[:16]
    key = f"{clean_prefix}_{digest}"
    return key[:64]


def get_doc(key: str, *, ttl_sec: float = 0.0) -> Any:
    """从内存或 MySQL app_documents 读取文档。"""
    ensure_migrated()
    now = time.time()
    with _LOCK:
        hit = _MEM_CACHE.get(key)
        if hit is not None and (ttl_sec <= 0 or (now - hit[0]) < ttl_sec):
            if not _db_enabled() or ttl_sec > 0:
                return hit[1]

    if not _db_enabled():
        with _LOCK:
            hit = _MEM_CACHE.get(key)
            return hit[1] if hit is not None else None

    try:
        from runtime_documents import read_document

        rev, payload = read_document(key)
        if rev > 0 and payload is not None:
            with _LOCK:
                _MEM_CACHE[key] = (now, payload)
            return payload
    except Exception:
        pass
    with _LOCK:
        hit = _MEM_CACHE.get(key)
        if hit is not None:
            return hit[1]
    return None


def set_doc(key: str, payload: Any, *, async_write: bool = False) -> bool:
    """写入内存并同步/异步持久化到 MySQL app_documents。返回是否已入库（或入队）。"""
    now = time.time()
    with _LOCK:
        _MEM_CACHE[key] = (now, payload)

    if not _db_enabled():
        return False

    try:
        from runtime_documents import enqueue_document, write_merging

        if async_write:
            enqueue_document(key, payload)
            return True
        rev = write_merging(key, payload)
        return rev > 0
    except Exception:
        return False


def ensure_migrated() -> None:
    global _MIGRATED
    if _MIGRATED:
        return
    with _LOCK:
        if _MIGRATED:
            return
        _MIGRATED = True
        try:
            migrate_and_cleanup_legacy_json()
        except Exception:
            pass


def migrate_and_cleanup_legacy_json() -> None:
    """将旧的本地 JSON 缓存迁移至数据库并清理磁盘上的遗留 .json 文件。"""
    now = time.time()
    with _LOCK:
        # 1. 迁移同花顺代码映射表
        ths_files = {
            "industry_codes": CACHE_DIR / "ths_industry_codes.json",
            "concept_codes": CACHE_DIR / "ths_concept_codes.json",
            "concept_clids": CACHE_DIR / "ths_concept_clids.json",
        }
        ths_bundle: dict[str, Any] = {}
        if _db_enabled():
            try:
                from runtime_documents import read_document

                rev, existing = read_document("sectors_ths_codes")
                if rev > 0 and isinstance(existing, dict):
                    ths_bundle.update(existing)
                    _MEM_CACHE["sectors_ths_codes"] = (now, ths_bundle)
            except Exception:
                pass

        changed_ths = False
        loaded_ths_files: list[Path] = []
        for field, path in ths_files.items():
            if path.is_file():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict) and raw.get("items"):
                        if not ths_bundle.get(field):
                            ths_bundle[field] = raw
                            changed_ths = True
                        loaded_ths_files.append(path)
                except Exception:
                    pass
        if ths_bundle:
            _MEM_CACHE["sectors_ths_codes"] = (now, ths_bundle)
            saved = set_doc("sectors_ths_codes", ths_bundle) if changed_ths else bool(ths_bundle)
            if saved and _db_enabled():
                for p in loaded_ths_files:
                    try:
                        p.unlink(missing_ok=True)
                    except OSError:
                        pass

        # 2. 迁移成分股索引
        idx_path = CACHE_DIR / "tdx_members_index.json"
        if idx_path.is_file():
            try:
                raw = json.loads(idx_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and raw.get("概念"):
                    doc_val = {
                        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "data": raw,
                    }
                    _MEM_CACHE["sectors_members_index"] = (now, doc_val)
                    if set_doc("sectors_members_index", doc_val) and _db_enabled():
                        idx_path.unlink(missing_ok=True)
                        (CACHE_DIR / "tdx_members_meta.json").unlink(missing_ok=True)
            except Exception:
                pass

        # 3. 迁移并清理板块轮动与实时快照 JSON
        rot_json = CACHE_DIR / "tdx_rotation_api.json"
        if rot_json.is_file():
            try:
                raw = json.loads(rot_json.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and raw.get("kinds"):
                    _MEM_CACHE["sectors_rotation_api"] = (now, raw)
                    if set_doc("sectors_rotation_api", raw) and _db_enabled():
                        rot_json.unlink(missing_ok=True)
            except Exception:
                pass

        fast_json = DATA_CACHE_DIR / "sectors_live_fast.json"
        if fast_json.is_file():
            try:
                raw = json.loads(fast_json.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and raw.get("conceptToday"):
                    _MEM_CACHE["sectors_live_fast"] = (now, raw)
                    if set_doc("sectors_live_fast", raw) and _db_enabled():
                        fast_json.unlink(missing_ok=True)
            except Exception:
                pass

        # 4. 清理其它遗留的本地 JSON 缓存文件（仅在数据库可连接时删除）
        if _db_enabled():
            try:
                from runtime_documents import read_document

                read_document("sectors_ths_codes")
                db_reachable = True
            except Exception:
                db_reachable = False
            if db_reachable:
                for pat in (
                    CACHE_DIR.glob("concept_leaders_*.json"),
                    CACHE_DIR.glob("leader_score_*.json"),
                    CACHE_DIR.glob("limitup_*.json"),
                    SNAP_DIR.glob("*.json"),
                ):
                    for p in pat:
                        try:
                            p.unlink(missing_ok=True)
                        except OSError:
                            pass
