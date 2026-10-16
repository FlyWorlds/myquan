"""Bounded, asynchronous recording of complete account valuations; no trading writes."""
from __future__ import annotations

import copy
import json
import math
import os
import queue
import threading
import time
from datetime import datetime
from typing import Any
from urllib.request import Request, urlopen

_QUEUE: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
_LOCK = threading.Lock()
_STARTED = False
_LAST_KEY: str | None = None
_ERROR_AT = 0.0


def build_sample(snapshot: dict[str, Any], *, session: str, revision: int) -> dict[str, Any] | None:
    account = snapshot.get("account")
    if snapshot.get("boot") or not isinstance(account, dict) or revision <= 0:
        return None
    for key in ("accountTotal", "availableCash", "totalPnl"):
        value = account.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            return None
    rows = snapshot.get("holdings") or []
    if not isinstance(rows, list):
        return None
    holdings = []
    closed = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        try:
            qty = int(row.get("持仓") or 0)
        except (ValueError, TypeError):
            return None
        if qty < 0:
            return None
        if qty > 0:
            mark = row.get("现价")
            if not isinstance(mark, (int, float)) or not math.isfinite(mark) or mark <= 0:
                return None
            holdings.append(row)
        elif row.get("已实现"):
            closed.append(row)
    observed = str(snapshot.get("clock") or "")
    try:
        datetime.strptime(session, "%Y-%m-%d")
        at = datetime.strptime(observed, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return copy.deepcopy(dict(tradingDay=session, observedAt=at.isoformat(), revision=revision,
                              account=account, holdings=holdings, closed=closed))


def _post(sample: dict[str, Any]) -> None:
    base = os.environ.get("PAPER_BACKEND_URL", "http://127.0.0.1:8080").rstrip("/")
    body = json.dumps(sample, ensure_ascii=False, allow_nan=False).encode("utf-8")
    req = Request(base + "/api/paper/account-snapshots", data=body, method="POST",
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=5) as response:
        json.load(response)


def _worker() -> None:
    global _LAST_KEY, _ERROR_AT
    while True:
        sample = _QUEUE.get()
        key = sample["tradingDay"] + ":" + sample["observedAt"]
        try:
            if key != _LAST_KEY:
                _post(sample)
                _LAST_KEY = key
        except Exception as exc:
            now = time.monotonic()
            if now - _ERROR_AT > 60:
                print(f"[ACCOUNT_SNAPSHOT] recording unavailable ({type(exc).__name__}); trading ledger unchanged")
                _ERROR_AT = now
        finally:
            _QUEUE.task_done()


def enqueue_account_snapshot(snapshot: dict[str, Any], *, session: str, revision: int) -> None:
    global _STARTED
    sample = build_sample(snapshot, session=session, revision=revision)
    if sample is None:
        return
    with _LOCK:
        if not _STARTED:
            threading.Thread(target=_worker, name="account-history", daemon=True).start()
            _STARTED = True
        try:
            _QUEUE.put_nowait(sample)
        except queue.Full:
            pass  # Never let monitoring backpressure block execution or grow an unbounded backlog.
