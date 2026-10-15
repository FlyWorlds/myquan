"""Persist received quotes before publishing them to trading consumers; no local write fallback."""
from __future__ import annotations

import copy
import json
import math
import os
import queue
import threading
import time
from datetime import datetime
from urllib.request import Request, urlopen

from condition_buy import timestamp

FIELDS = ("session", "open", "high", "low", "last", "prev_close", "day_chg_pct", "last_ts",
          "_quote_source", "_source_time_verified", "_received_at", "_open_finalized", "_preopen_baseline",
          "_auction_baseline", "_auction_high", "_auction_low", "_auction_ts")


def read_quotes():
    base = os.environ.get("PAPER_BACKEND_URL", "http://127.0.0.1:8080").rstrip("/")
    with urlopen(base+"/api/market-quotes", timeout=2) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError("Invalid database quote read response")
    return result


def same_observation(sent, confirmed):
    return all(sent.get(key) == confirmed.get(key) for key in (
        "session", "last_ts", "_quote_source", "open", "high", "low", "last", "prev_close"))


def write_quotes(batch):
    base = os.environ.get("PAPER_BACKEND_URL", "http://127.0.0.1:8080").rstrip("/")
    request = Request(base+"/api/market-quotes", data=json.dumps(batch, allow_nan=False).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=2) as response:
        result = json.load(response)
    if not isinstance(result, list) or len(result) != len(batch):
        raise ValueError("Invalid database quote acknowledgement")
    return result


class DatabaseQuotes:
    def __init__(self, *, stop, on_committed, log=print):
        self.stop, self.on_committed, self.log = stop, on_committed, log
        self.events = queue.Queue(maxsize=2048)
        self.lock = threading.RLock()
        self._quotes = {}
        self.ready, self.error = False, None
        self.dropped = 0
        self.rejected = 0
        self.expired = 0
        self.last_write_ms = None
        self.latest_quote_at = None
        self.read_error = None
        self.reference_ready = False

    def refresh(self):
        """Restore committed reference prices, never dispatch historical observations."""
        try:
            quotes = read_quotes()
            for sina, quote in quotes.items():
                if (not isinstance(quote, dict) or quote.get("_database_quote_symbol") != sina
                        or not isinstance(quote.get("_database_quote_revision"), int)
                        or quote["_database_quote_revision"] <= 0
                        or quote.get("_source_time_verified") is not True
                        or not timestamp(quote.get("last_ts"))):
                    raise ValueError("Invalid database reference quote")
            with self.lock:
                for sina, quote in quotes.items():
                    old = self._quotes.get(sina, {})
                    if quote["_database_quote_revision"] > old.get("_database_quote_revision", 0):
                        self._quotes[sina] = dict(copy.deepcopy(quote), _reference_only=True)
            self.reference_ready = True
            self.read_error = None
        except Exception as exc:
            self.read_error = str(exc)
            self.log(f"[QUOTE_DB] Reference read failed; no local file fallback: {type(exc).__name__}")

    def get(self, sina, *, executable=False):
        with self.lock:
            quote = self._quotes.get(sina)
            if executable and quote and quote.get("_reference_only"):
                return None
            return copy.deepcopy(quote)

    def status(self):
        at = timestamp(self.latest_quote_at)
        age = (datetime.now()-at).total_seconds() if at else None
        return dict(source="mysql", ready=self.ready, error=self.error,
                    pending=self.events.qsize(), dropped=self.dropped, rejected=self.rejected, expired=self.expired,
                    writeMs=self.last_write_ms, readError=self.read_error, referenceReady=self.reference_ready,
                    latestQuoteAt=self.latest_quote_at, quoteAgeSec=age,
                    fresh=age is not None and 0 <= age <= 5)

    def observe(self, sina, quote):
        if self.stop.is_set() or quote.get("_source_time_verified") is not True:
            return
        try:
            if (quote.get("_quote_source") != "sina_batch"
                    or not all(math.isfinite(float(quote[k])) and float(quote[k]) > 0
                               for k in ("open", "high", "low", "last", "prev_close"))
                    or float(quote["low"]) > min(float(quote["open"]), float(quote["last"]))
                    or float(quote["high"]) < max(float(quote["open"]), float(quote["last"]))):
                self.rejected += 1
                return
        except (KeyError, TypeError, ValueError, OverflowError):
            self.rejected += 1
            return
        clean = {key: quote[key] for key in FIELDS if key in quote}
        if not clean.get("_received_at"):
            clean["_received_at"] = datetime.now().isoformat(sep=" ", timespec="microseconds")
        try:
            self.events.put_nowait((dict(symbol=sina, quote=clean), time.monotonic()+5))
        except queue.Full:
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 100 == 0:
                self.log(f"[QUOTE_DB] Queue full; discarded {self.dropped}, no historical fills")

    def flush(self):
        batch = []
        while len(batch) < 64:
            try:
                item, deadline = self.events.get_nowait()
                if time.monotonic() > deadline:
                    self.expired += 1
                    continue
                batch.append(item)
            except queue.Empty:
                break
        if not batch:
            return
        started = time.monotonic()
        try:
            committed = write_quotes(batch)
            # Validate the complete response before any execution consumer sees it.
            for sent, quote in zip(batch, committed):
                if (not isinstance(quote, dict) or not isinstance(quote.get("_database_quote_revision"), int)
                        or quote.get("_database_quote_symbol") != sent["symbol"]
                        or quote["_database_quote_revision"] <= 0 or quote.get("_source_time_verified") is not True
                        or not timestamp(quote.get("last_ts")) or not timestamp(quote.get("_received_at"))
                        or quote.get("session") != quote["last_ts"][:10]
                        or quote["last_ts"] < sent["quote"]["last_ts"]):
                    raise ValueError("Invalid committed quote")
            self.ready, self.error = True, None
            self.last_write_ms = round((time.monotonic()-started)*1000, 1)
            for sent, quote in zip(batch, committed):
                sina = sent["symbol"]
                observed = same_observation(sent["quote"], quote)
                with self.lock:
                    old = self._quotes.get(sina, {})
                    revision, prior = quote["_database_quote_revision"], old.get("_database_quote_revision", 0)
                    if revision < prior or (revision == prior and (not old.get("_reference_only") or not observed)):
                        continue
                    self._quotes[sina] = dict(copy.deepcopy(quote), _reference_only=not observed)
                    if observed:
                        self.latest_quote_at = max(self.latest_quote_at or "", quote["last_ts"])
                if not observed:
                    continue  # A newer shared DB snapshot is a reference, not this receiver's event.
                try:
                    self.on_committed(sina, copy.deepcopy(quote))
                except Exception as exc:
                    self.log(f"[QUOTE_DB] Consumer failed {sina}: {type(exc).__name__}; no invented replay")
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self.log(f"[QUOTE_DB] Write/dispatch failed; no local execution fallback: {self.error}")

    def run(self):
        while not self.stop.is_set():
            self.flush()
            self.stop.wait(.1 if not self.error else 1.)
