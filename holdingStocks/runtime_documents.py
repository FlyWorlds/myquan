"""MySQL document and voided-event access through the Java API.

Production reads and writes go to the database. Offline tests keep HOLDINGS_STORAGE=local_json
and do not call this module. A failed database call does not fall back to a local file.
"""
from __future__ import annotations

import json
import math
import os
import threading
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class DocumentStoreError(RuntimeError):
    pass


def _base() -> str:
    return os.environ.get("PAPER_BACKEND_URL", "http://127.0.0.1:8080").rstrip("/")


def _sanitize(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _request(method: str, path: str, payload: Any = None, *, timeout: float = 8) -> Any:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    request = Request(_base() + path, data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 409:
            raise DocumentStoreError("document revision conflict") from exc
        raise DocumentStoreError(f"document request rejected (HTTP {exc.code})") from exc
    except (OSError, URLError, ValueError) as exc:
        raise DocumentStoreError("document store unavailable") from exc


def read_document(key: str) -> tuple[int, Any]:
    result = _request("GET", "/api/documents/" + key)
    if not isinstance(result, dict):
        raise DocumentStoreError("invalid document response")
    revision = int(result.get("revision") or 0)
    payload = result.get("payload")
    if revision <= 0 or payload is None:
        return 0, None
    return revision, payload


def write_document(key: str, payload: Any, expected_revision: int, *, request_id: str | None = None) -> int:
    body = {
        "expectedRevision": int(expected_revision),
        "requestId": request_id or uuid.uuid4().hex,
        "payload": _sanitize(payload),
    }
    result = _request("PUT", "/api/documents/" + key, body)
    if not isinstance(result, dict) or "revision" not in result:
        raise DocumentStoreError("invalid document write response")
    return int(result["revision"])


def write_merging(key: str, payload: Any) -> int:
    """Last complete document wins. One reload retry covers a concurrent publisher."""
    revision, _current = read_document(key)
    try:
        return write_document(key, payload, revision)
    except DocumentStoreError as exc:
        if "conflict" not in str(exc):
            raise
        revision, _current = read_document(key)
        return write_document(key, payload, revision)


def append_voided(events: list[dict[str, Any]]) -> int:
    inserted = 0
    batch: list[dict[str, Any]] = []
    for event in events:
        batch.append(_sanitize(event))
        if len(batch) == 400:
            inserted += _post_voided(batch)
            batch = []
    if batch:
        inserted += _post_voided(batch)
    return inserted


def _post_voided(events: list[dict[str, Any]]) -> int:
    result = _request("POST", "/api/strategy-simulator/voided", {"events": events}, timeout=30)
    if not isinstance(result, dict):
        raise DocumentStoreError("invalid voided-event response")
    return int(result.get("inserted") or 0)


def voided_count() -> int:
    result = _request("GET", "/api/strategy-simulator/voided/count")
    return int(result.get("count") or 0) if isinstance(result, dict) else 0


_PENDING: dict[str, Any] = {}
_PENDING_LOCK = threading.Lock()
_WORKER: threading.Thread | None = None


def enqueue_document(key: str, payload: Any) -> None:
    """Coalesce rapid snapshot publishes. The caller does not wait on the database."""
    global _WORKER
    with _PENDING_LOCK:
        _PENDING[key] = _sanitize(payload)
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_drain, name="runtime-documents", daemon=True)
            _WORKER.start()


def _drain() -> None:
    while True:
        with _PENDING_LOCK:
            if not _PENDING:
                return
            key, payload = _PENDING.popitem()
        try:
            write_merging(key, payload)
        except DocumentStoreError as exc:
            print(f"[runtime-documents] {key} 入库失败: {exc}")
