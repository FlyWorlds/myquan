"""Strategy16 virtual books: database-authoritative, independent of paper account slots."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class StrategyDatabaseError(RuntimeError):
    pass


def request_books(method="GET", payload=None, *, suffix="", strategy_id=None):
    from watch_config import STRATEGY_ID
    strategy_id = strategy_id or STRATEGY_ID
    if strategy_id not in ("strategy1", "strategy16"):
        raise StrategyDatabaseError("Unsupported strategy book")
    base = os.environ.get("PAPER_BACKEND_URL", "http://127.0.0.1:8080").rstrip("/")
    body = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    req = Request(base+f"/api/strategy-books/{strategy_id}"+suffix, data=body, method=method,
                  headers={"Content-Type": "application/json"})
    for attempt in range(2):
        try:
            with urlopen(req, timeout=2) as response:
                return json.load(response)
        except HTTPError as exc:
            raise StrategyDatabaseError(f"Strategy database HTTP {exc.code}; no local fallback") from exc
        except (OSError, URLError, ValueError) as exc:
            if attempt:
                raise StrategyDatabaseError("Strategy database unavailable; no local fallback") from exc


class StrategyBooksClient:
    def __init__(self, strategy_id=None):
        from watch_config import STRATEGY_ID
        self.strategy_id = strategy_id or STRATEGY_ID
        self.lock = threading.RLock()
        self._books = {}
        self.ready = False
        self.error = None

    def refresh(self):
        try:
            result = request_books(strategy_id=self.strategy_id)
            if not isinstance(result, dict) or any(not isinstance(v, dict)
                    or v.get("strategy_id", self.strategy_id) != self.strategy_id for v in result.values()):
                raise StrategyDatabaseError("Invalid strategy books response")
            with self.lock:
                for code, book in result.items():
                    if int(book.get("revision") or 0) >= int(self._books.get(code, {}).get("revision") or 0):
                        self._books[code] = copy.deepcopy(book)
                self.ready, self.error = True, None
        except Exception as exc:
            self.error = str(exc)
            raise

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self._books)

    def get(self, code):
        with self.lock:
            return copy.deepcopy(self._books.get(code, {}))

    def command(self, code, book, *, quote, now, side="MARK", price=None, qty=None, state=None, reason=""):
        payload = dict(expectedRevision=int(book.get("revision") or 0), side=side, price=price, qty=qty,
            mark=float(quote["last"]), quoteAt=str(quote["last_ts"]),
            decisionAt=now.strftime("%Y-%m-%d %H:%M:%S"), state=state or {}, reason=reason)
        token = json.dumps(dict(strategy_id=self.strategy_id, code=code, **payload), sort_keys=True, allow_nan=False)
        payload["requestId"] = hashlib.sha256(token.encode()).hexdigest()
        try:
            committed = request_books("POST", payload, suffix="/"+code, strategy_id=self.strategy_id)
            if (not isinstance(committed, dict) or committed.get("symbol") != code or "revision" not in committed
                    or committed.get("strategy_id", self.strategy_id) != self.strategy_id):
                raise StrategyDatabaseError("Invalid strategy write response")
        except Exception as exc:
            self.error = str(exc)
            # An ambiguous write is resolved from the database, never from local guessed state.
            try:
                self.refresh()
            except StrategyDatabaseError:
                pass
            raise
        with self.lock:
            self._books[code] = copy.deepcopy(committed)
            self.error = None
        return committed


def apply_database_book_to_row(row, book):
    from strategy_simulator import apply_book_to_row
    apply_book_to_row(row, book)
    row.update({"策略收益来源": "database_strategy_book", "策略账本ID": book.get("strategy_id") or "strategy16", "策略账本版本": book["revision"],
        "策略历史状态": book.get("history_status"), "策略收益待回测更新": False,
        "策略收益语义": "database_cash_plus_market_value", "策略收益": book.get("total_pnl"),
        "综合策略收益": book.get("total_pnl"), "策略收益%": book.get("cumulative_return_pct"),
        "综合策略收益%": book.get("cumulative_return_pct"), "策略单笔收益": book.get("cycle_pnl"),
        "策略单笔收益%": book.get("cycle_return_pct"), "单笔收入%": book.get("single_return_pct"),
        "本轮浮动盈亏": book.get("unrealized_pnl"), "策略历史检查点盈亏": book.get("checkpoint_total_pnl")})
    row["策略估值时刻"] = book.get("last_quote_ts")
    row["策略估值价格"] = book.get("last_mark")
    row["策略入库后增量盈亏"] = book.get("since_checkpoint_pnl")
