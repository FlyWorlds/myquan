"""Prepared paper buy-stop orders; no historical replay or network work on tick delivery."""
from __future__ import annotations

import hashlib
import math
import queue
import threading
from datetime import datetime
from typing import Any, Callable


def timestamp(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value))
        return result if result.tzinfo is None else None
    except (TypeError, ValueError):
        return None


def fresh_quote(quote: dict, session: str, now: datetime, max_age: float = 5.0) -> bool:
    at = timestamp(quote.get("last_ts"))
    try:
        return bool(at and quote.get("session") == session and at.date() == now.date()
                and 0 <= (now - at).total_seconds() <= max_age
                and not quote.get("_preopen_baseline") and quote.get("_open_finalized") is not False
                and quote.get("_source_time_verified") is not False
                and not quote.get("_reference_only")
                and quote.get("_quote_source") not in ("seed", "daily_prev")
                and all(math.isfinite(float(quote.get(key) or 0)) and float(quote.get(key) or 0) > 0
                        for key in ("open", "last", "high", "low"))
                and float(quote["low"]) <= min(float(quote["open"]), float(quote["last"])) + 1e-8
                and float(quote["high"]) + 1e-8 >= max(float(quote["open"]), float(quote["last"])))
    except (TypeError, ValueError, OverflowError):
        return False


def make_order(*, code: str, session: str, open_px: float, price: float, entry_pct: float,
               tick: float, armed_at: str, quote_at: str, name: str, market: str,
               kind: str = "breakout") -> dict:
    from watch_config import STRATEGY_ID
    identity = f"{STRATEGY_ID}:{session}:{code}:{open_px:.4f}:{price:.4f}:{kind}"
    return dict(id=hashlib.sha256(identity.encode()).hexdigest()[:24], strategy=STRATEGY_ID,
                code=code, name=name, market=market, session=session, open=open_px,
                price=price, entry_pct=entry_pct, tick=tick, armed_at=armed_at,
                armed_quote_at=quote_at, status="ARMED", kind=kind,
                signal_factor="factor29" if kind == "auction_open" else "factor26",
                fill_assumption="paper_stop_at_order_price")


def auction_entry_blocked(open_px, prev_close, *, limit_up_pct=.10) -> bool:
    """Conservative auction exclusion, not proof of an all-day one-word board."""
    try:
        opening, previous, limit = float(open_px), float(prev_close), float(limit_up_pct)
        return (all(math.isfinite(v) and v > 0 for v in (opening, previous, limit))
                and opening / previous - 1 >= limit - .003 - 1e-12)
    except (TypeError, ValueError, OverflowError):
        return False


def is_trigger(order: dict, quote: dict, received_at: datetime, now: datetime) -> bool:
    if order.get("status") not in ("ARMED", "TRIGGERED"):
        return False
    if not 0 <= (now - received_at).total_seconds() <= 5:
        return False
    session = str(order.get("session") or "")
    try:
        if not fresh_quote(quote, session, now):
            return False
        if auction_entry_blocked(quote.get("open"), quote.get("prev_close"),
                                 limit_up_pct=order.get("limit_up_pct") or .10):
            return False
        at = timestamp(quote.get("last_ts"))
        armed = timestamp(order.get("armed_at"))
        boundary = timestamp(order.get("armed_quote_at"))
        if not armed or not at or not boundary or at < armed or at <= boundary:
            return False
        clock = at.strftime("%H:%M:%S")
        if not ("09:30:00" <= clock <= "11:30:00" or "13:00:00" <= clock < "15:00:00"):
            return False
        # An open-fill auction order must have been prepared before the open and
        # observed immediately at the bell; late quotes cannot backfill that price.
        if order.get("kind") == "auction_open" and not (
                armed.strftime("%H:%M:%S") < "09:30:00" and clock <= "09:30:05"):
            return False
        price = float(order["price"])
        return (abs(float(quote["open"]) - float(order["open"])) <= max(1e-8, float(order["tick"]) / 10)
                and float(quote["last"]) + 1e-12 >= price
                and float(quote["low"]) <= price + 1e-12 <= float(quote["high"]) + 1e-12)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


class ConditionBuyWorker:
    def __init__(self, *, stop: threading.Event, execute: Callable, log: Callable):
        self.stop, self.execute, self.log = stop, execute, log
        self.events = queue.Queue(maxsize=2048)
        self._codes: frozenset[str] = frozenset()
        self.dropped = 0
        self.expired = self.failures = self.processed = 0
        self.last_evaluated_at = None
        self.last_source_at = None
        self.last_queue_ms = None

    def status(self):
        return dict(pending=self.events.qsize(), dropped=self.dropped, expired=self.expired,
                    failures=self.failures, processed=self.processed, lastEvaluatedAt=self.last_evaluated_at,
                    lastSourceAt=self.last_source_at, queueAgeMs=self.last_queue_ms)

    def watch(self, sinas):
        self._codes = frozenset(str(s).lower() for s in sinas)

    def observe(self, sina: str, quote: dict):
        if sina not in self._codes or self.stop.is_set():
            return
        try:
            received = timestamp(quote.get("_received_at")) or datetime.now()
            self.events.put_nowait((sina, dict(quote), received))
        except queue.Full:
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 100 == 0:
                self.log(f"[CONDITION_BUY] 报价队列满，已丢弃{self.dropped}条；不补造历史成交")

    def run(self):
        while not self.stop.is_set():
            try:
                event = self.events.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                now = datetime.now()
                age = (now-event[2]).total_seconds()
                self.last_queue_ms = round(age*1000, 1)
                if not 0 <= age <= 5:
                    self.expired += 1
                    continue
                self.execute(*event)
                self.processed += 1
                after = datetime.now()
                if fresh_quote(event[1], str(event[1].get("session")), after):
                    self.last_evaluated_at = after.strftime("%Y-%m-%d %H:%M:%S")
                    self.last_source_at = event[1]["last_ts"]
            except Exception as exc:
                self.failures += 1
                self.log(f"[CONDITION_BUY] 执行失败，未回退旧扫描买入: {type(exc).__name__}: {exc}")

