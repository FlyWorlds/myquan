"""行情源健康度：断网后 quoteStale，午休无成交只要新浪/SSE 还通就不红。"""

from __future__ import annotations

import time
import unittest

import sys
from pathlib import Path

_HS = Path(__file__).resolve().parent
if str(_HS) not in sys.path:
    sys.path.insert(0, str(_HS))

from quote_feed import QuoteHub
from watch_snapshot import apply_feed_health


class TestQuoteHealth(unittest.TestCase):
    def test_no_tick_yet_not_stale(self) -> None:
        hub = QuoteHub()
        h = hub.quote_health(max_age_sec=40)
        self.assertFalse(h["feedOk"])
        self.assertFalse(h["quoteStale"])
        self.assertIsNone(h["quoteAt"])

    def test_recent_tick_ok(self) -> None:
        hub = QuoteHub()
        hub.mark_quote_ok("sina_batch")
        h = hub.quote_health(max_age_sec=40)
        self.assertTrue(h["feedOk"])
        self.assertFalse(h["quoteStale"])
        self.assertTrue(h["quoteAt"])

    def test_old_tick_stale(self) -> None:
        hub = QuoteHub()
        hub.mark_quote_ok("em_sse")
        hub.quote_last_ok_ts = time.time() - 90
        h = hub.quote_health(max_age_sec=40)
        self.assertFalse(h["feedOk"])
        self.assertTrue(h["quoteStale"])
        self.assertTrue(h["quoteAt"])

    def test_sina_ok_does_not_mark_sse_healthy(self) -> None:
        hub = QuoteHub()
        hub.mark_quote_ok("sina_batch")
        self.assertFalse(hub.sse_healthy())

    def test_apply_feed_health_keep_stale(self) -> None:
        snap = {"clock": "2026-09-14 12:01:00"}
        apply_feed_health(
            snap,
            {"feedOk": True, "quoteStale": False, "quoteAt": "12:00"},
            keep_stale=True,
        )
        self.assertTrue(snap["quoteStale"])
        self.assertTrue(snap["feedOk"])


if __name__ == "__main__":
    unittest.main()
