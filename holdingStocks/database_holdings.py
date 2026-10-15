"""Database-authoritative paper ledger over the local Spring Boot API.

No JSON fallback writes. Revision conflicts abort rather than merging cash/positions.
The legacy file store is retained only for explicit offline tests and migration.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from functools import wraps
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from holdings_store import HoldingsStore, sync_inplace


class DatabaseStateError(RuntimeError):
    pass


def database_enabled() -> bool:
    mode = os.environ.get("HOLDINGS_STORAGE", "database")
    if mode not in {"database", "local_json"}:
        raise ValueError("HOLDINGS_STORAGE must be database or local_json")
    return mode == "database"


def request_state(method: str = "GET", payload: Any = None, *, suffix: str = "") -> dict[str, Any]:
    base = os.environ.get("PAPER_BACKEND_URL", "http://127.0.0.1:8080").rstrip("/")
    body = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    request = Request(base + "/api/paper/state" + suffix, data=body, method=method,
                      headers={"Content-Type": "application/json"})
    # PUT retries reuse the same request ID; the backend commits it at most once.
    for attempt in range(2 if method == "PUT" else 1):
        try:
            with urlopen(request, timeout=5) as response:
                result = json.load(response)
            if not isinstance(result, dict) or not isinstance(result.get("holdings"), dict):
                raise DatabaseStateError("Invalid database ledger response")
            return result
        except HTTPError as exc:
            if exc.code == 409:
                raise DatabaseStateError("Database revision conflict; reload before retrying the operation") from exc
            raise DatabaseStateError(f"Database ledger request rejected (HTTP {exc.code}); no local fallback") from exc
        except (OSError, URLError, ValueError) as exc:
            if attempt == 0 and method == "PUT":
                continue
            raise DatabaseStateError("Database ledger unavailable; paper writes blocked, no local fallback") from exc
    raise DatabaseStateError("Database ledger unavailable")


class DatabaseHoldingsStore(HoldingsStore):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._state: dict[str, Any] | None = None
        self._read_at = 0.0
        self._transaction_depth = 0
        self._read_model = None

    def _accept(self, state: dict[str, Any]) -> dict[str, Any]:
        if self._state is None or state["revision"] != self._state["revision"]:
            self._read_model = None
        cur = self.cache.get("data")
        if not isinstance(cur, dict):
            cur = copy.deepcopy(state["holdings"])
        else:
            sync_inplace(cur, state["holdings"])
        self._state = copy.deepcopy(state)
        self._read_at = time.monotonic()
        self.cache.update(data=cur, path=str(self._path()), token=state["revision"],
                          base_text=json.dumps(state["holdings"], ensure_ascii=False),
                          mtime=float(state["revision"]))
        if self._normalize:
            self._normalize(cur)
        return cur

    def load(self, *, force: bool = False) -> dict[str, Any]:
        with self.lock:
            if self._transaction_depth and self.cache.get("data") is not None:
                return self.cache["data"]
            if not force and self.cache.get("data") is not None and time.monotonic() - self._read_at < 1:
                return self.cache["data"]
            state = request_state()
            if self._state is not None and self.cache.get("data") is not None and state["revision"] == self._state["revision"]:
                self._read_at = time.monotonic()
                return self.cache["data"]
            return self._accept(state)

    def save(self, data: dict[str, Any], *, stamp: Any = None,
             records: list[dict[str, Any]] | None = None, ledger: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.lock:
            if self._state is None:
                self.load(force=True)
            assert self._state is not None
            if data is not self.cache.get("data"):
                raise DatabaseStateError("Detached holdings object rejected; reload database state before writing")
            try:
                if stamp:
                    stamp(data)
                holdings = copy.deepcopy(data)
                trades = copy.deepcopy(self._state["trades"])
                delivery = copy.deepcopy(ledger if ledger is not None else self._state["ledger"])
                if records:
                    from trade_ledger import build_ledger_entry
                    for raw in records:
                        record = dict(raw)
                        record.setdefault("id", uuid.uuid4().hex)
                        trades.append(record)
                        entry = build_ledger_entry(record, holdings=holdings)
                        if entry.get("side") in {"buy", "sell"}:
                            delivery.setdefault("entries", []).append(entry)
                    delivery["updated_at"] = holdings.get("updated_at")
                payload = dict(expectedRevision=self._state["revision"], requestId=uuid.uuid4().hex,
                               holdings=holdings, trades=trades, ledger=delivery)
                return self._accept(request_state("PUT", payload))
            except Exception:
                # Do not leave failed/ambiguous mutations looking like committed positions in memory.
                self._accept(self._state)
                self._read_at = 0
                raise

    def trades(self) -> list[dict[str, Any]]:
        with self.lock:
            self.load()
            assert self._state is not None
            return copy.deepcopy(self._state["trades"])

    def snapshot(self) -> dict[str, Any]:
        """One committed revision for cash, positions, deliveries and corrections."""
        with self.lock:
            self.load()
            assert self._state is not None
            return copy.deepcopy(self._state)

    def read_model(self):
        with self.lock:
            self.load()
            assert self._state is not None
            if self._read_model is None:
                from account_reconciliation import AccountReadModel
                self._read_model = AccountReadModel(copy.deepcopy(self._state))
            return self._read_model

    def ledger(self) -> dict[str, Any]:
        with self.lock:
            self.load()
            assert self._state is not None
            return copy.deepcopy(self._state["ledger"])

    def reset_session_trades(self, session: str, data: dict[str, Any], *, stamp: Any) -> int:
        with self.lock:
            assert self._state is not None
            if data is not self.cache.get("data"):
                raise DatabaseStateError("Detached reset state rejected")
            try:
                # Never refresh between mutation and commit: use the version loaded before reset.
                trades = copy.deepcopy(self._state["trades"])
                archived = [r for r in trades if not r.get("reset_archived")
                            and str(r.get("time") or r.get("ts") or "").startswith(session)]
                for row in archived:
                    row["reset_archived"] = True
                stamp(data)
                payload = dict(expectedRevision=self._state["revision"], requestId=uuid.uuid4().hex,
                               holdings=copy.deepcopy(data), trades=trades, ledger=copy.deepcopy(self._state["ledger"]))
                self._accept(request_state("PUT", payload))
            except Exception:
                self._accept(self._state)
                self._read_at = 0
                raise
            return len(archived)

    def reload_from_disk(self) -> dict[str, Any]:
        with self.lock:
            return self._accept(request_state())

    def transaction(self):
        import contextlib

        @contextlib.contextmanager
        def scope():
            with self.lock:
                if not self._transaction_depth:
                    self.load(force=True)
                self._transaction_depth += 1
                try:
                    yield
                except Exception:
                    if self._state is not None:
                        self._accept(self._state)
                    self._read_at = 0
                    raise
                finally:
                    self._transaction_depth -= 1
        return scope()


def paper_mutation(function):
    """Serialize read/modify/write on the stable shared holdings object."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        import sys
        module = sys.modules[function.__module__]
        with module._HOLDINGS_STORE.transaction():
            return function(*args, **kwargs)
    return wrapped
