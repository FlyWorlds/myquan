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
        self.assertEqual(h["dataSources"], ["sina_batch"])
        self.assertIn("sina_batch", h["sourceAges"])

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

    def test_one_fresh_symbol_cannot_hide_another_stale_symbol(self):
        from unittest.mock import patch
        from datetime import datetime
        now = datetime(2026, 10, 26, 10, 0)
        hub = QuoteHub()
        hub.expected_symbols = ['sz000001', 'sz000002']
        hub.apply_tick('sz000001', last=10.2, open_px=10., high=10.3, low=10.,
                       prev_close=10., last_ts='2026-10-26 10:00:00', source='sina_batch')
        hub.apply_tick('sz000002', last=10.2, open_px=10., high=10.3, low=10.,
                       prev_close=10., last_ts='2026-10-26 09:58:00', source='sina_batch')
        hub.mark_quote_ok('sina_batch')
        with patch('watch_config.market_phase', return_value='continuous'), patch('quote_feed.datetime') as clock:
            clock.now.return_value = now
            health = hub.quote_health()
        self.assertTrue(health['feedOk'])
        self.assertTrue(health['quotePartial'])
        self.assertEqual(health['staleSymbols'], ['sz000002'])

    def test_apply_feed_health_keep_stale(self) -> None:
        snap = {"clock": "2026-09-14 12:01:00"}
        apply_feed_health(
            snap,
            {
                "feedOk": True,
                "quoteStale": False,
                "quoteAt": "12:00",
                "dataSources": ["sina_batch"],
                "sourceAges": {"sina_batch": {"ageSec": 1.0}},
            },
            keep_stale=True,
        )
        self.assertTrue(snap["quoteStale"])
        self.assertTrue(snap["feedOk"])
        self.assertEqual(snap["dataSources"], ["sina_batch"])
        self.assertIn("sina_batch", snap["sourceAges"])

    def test_0925_resets_auction_open_high_low(self) -> None:
        """9:15–9:25 指示价不得污染正式开盘及其后买点。"""
        hub = QuoteHub()
        hub.apply_tick(
            "sz002580",
            last=17.90,
            open_px=17.90,
            high=18.20,
            low=17.70,
            prev_close=17.80,
            last_ts="2026-10-13 09:20:00",
            source="sina_batch",
        )
        pre = hub.get_quote("sz002580")
        self.assertFalse(pre["_open_finalized"])
        self.assertTrue(pre["_preopen_baseline"])

        hub.apply_tick(
            "sz002580",
            last=19.00,
            open_px=19.00,
            high=19.00,
            low=19.00,
            prev_close=17.80,
            last_ts="2026-10-13 09:25:01",
            source="sina_batch",
        )
        q = hub.get_quote("sz002580")
        self.assertTrue(q["_open_finalized"])
        self.assertFalse(q["_preopen_baseline"])
        self.assertEqual(q["open"], 19.00)
        self.assertEqual(q["high"], 19.00)
        self.assertEqual(q["low"], 19.00)

    def test_official_open_can_correct_nonzero_auction_open(self) -> None:
        """非零竞价 open 也必须被正式开盘纠正；旧实现只在 open<=0 时更新。"""
        hub = QuoteHub()
        hub.seed_from_quote(
            "sz002636",
            {
                "session": "2026-10-13",
                "open": 58.51,
                "high": 58.51,
                "low": 58.51,
                "last": 58.51,
                "prev_close": 58.20,
                "last_ts": "2026-10-13 09:24:59",
            },
        )
        hub.apply_tick(
            "sz002636",
            last=63.96,
            open_px=63.96,
            high=63.96,
            low=63.96,
            prev_close=58.20,
            last_ts="2026-10-13 09:30:00",
        )
        q = hub.get_quote("sz002636")
        self.assertEqual(q["open"], 63.96)
        self.assertGreaterEqual(q["low"], 63.96)

    def test_auction_lock_path_survives_0925_reset(self) -> None:
        hub = QuoteHub()
        hub.apply_tick(
            "sz002580",
            last=17.70,
            open_px=17.70,
            last_ts="2026-10-13 09:15:30",
        )
        hub.apply_tick(
            "sz002580",
            last=17.90,
            open_px=17.90,
            last_ts="2026-10-13 09:20:00",
        )
        hub.apply_tick(
            "sz002580",
            last=18.35,
            open_px=17.90,
            last_ts="2026-10-13 09:24:50",
        )
        pre = hub.get_quote("sz002580")
        self.assertAlmostEqual(float(pre["_auction_baseline"]), 17.90, places=2)
        self.assertAlmostEqual(float(pre["_auction_high"]), 18.35, places=2)
        hub.apply_tick(
            "sz002580",
            last=18.53,
            open_px=18.53,
            high=18.53,
            low=18.53,
            last_ts="2026-10-13 09:25:01",
        )
        q = hub.get_quote("sz002580")
        self.assertEqual(q["open"], 18.53)
        self.assertEqual(q["high"], 18.53)
        self.assertAlmostEqual(float(q["_auction_baseline"]), 17.90, places=2)
        self.assertAlmostEqual(float(q["_auction_high"]), 18.35, places=2)
        self.assertNotAlmostEqual(float(q["_auction_high"]), 18.53, places=2)


class TestExecutableQuoteIsolation(unittest.TestCase):
    def test_missing_raw_open_after_auction_cannot_become_an_official_trade_price(self):
        from unittest.mock import Mock, patch
        from quote_feed import fetch_sina_batch
        fields = ["0"]*32
        fields[0], fields[2], fields[3], fields[4], fields[5] = "Test", "10", "10.26", "10.3", "10"
        fields[30], fields[31] = "2026-10-15", "09:30:01"
        payload = ('var hq_str_sz000070="'+','.join(fields)+'";').encode("gbk")
        with patch("quote_feed._quote_http_get", return_value=Mock(content=payload)):
            spot = fetch_sina_batch(["sz000070"])["sz000070"]
        self.assertFalse(spot["_trade_quality_ok"])
        hub = QuoteHub()
        observer = Mock()
        hub.on_quote = observer
        hub.apply_tick("sz000070", last=spot["last"], open_px=spot["open"], high=spot["high"],
                       low=spot["low"], prev_close=spot["prev_close"], last_ts=spot["last_ts"],
                       source="sina_batch", source_time_verified=spot["_trade_quality_ok"])
        observer.assert_not_called()
        self.assertIsNone(hub.get_execution_quote("sz000070"))

    def test_slow_cold_batch_does_not_delay_the_hot_batchs_next_poll(self):
        import threading
        from unittest.mock import patch
        from quote_feed import SinaBatchPoller
        stop, release, cold_started, hot_twice = (threading.Event() for _ in range(4))
        hot = [f"sz{i:06d}" for i in range(50)]
        cold = ["sh600330"]
        counts = [0]
        def fetch(codes, **kwargs):
            self.assertEqual(kwargs["timeout"], (2, 3))
            if codes == cold:
                cold_started.set()
                release.wait(5)
            else:
                counts[0] += 1
                if counts[0] >= 2:
                    hot_twice.set()
            return {}
        poller = SinaBatchPoller(QuoteHub(), hot+cold, stop=stop, interval=1.)
        worker = threading.Thread(target=poller.run, daemon=True)
        with patch("quote_feed.fetch_sina_batch", side_effect=fetch), patch("quote_feed.fetch_tencent_batch", return_value={}), patch("watch_config.market_phase", return_value="closed"):
            worker.start()
            try:
                self.assertTrue(cold_started.wait(1))
                self.assertTrue(hot_twice.wait(2.5), "hot quotes waited for a slow unrelated batch")
            finally:
                stop.set()
                release.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())

    def test_receive_clock_only_sse_cannot_trigger_or_poison_executable_ohlc(self):
        from unittest.mock import Mock
        hub = QuoteHub()
        observer = Mock()
        hub.on_quote = observer
        hub.apply_tick("sz000070", last=10.2, open_px=10., high=10.3, low=10., prev_close=10.,
                       last_ts="2026-10-15 09:30:01", source="sina_batch")
        hub.apply_tick("sz000070", last=20., open_px=20., high=30., low=1., prev_close=10.,
                       last_ts="2026-10-15 09:30:02", source="em_sse")
        self.assertEqual(observer.call_count, 1)
        self.assertFalse(hub.get_quote("sz000070")["_source_time_verified"])
        self.assertEqual(hub.get_execution_quote("sz000070")["high"], 10.3)
        hub.apply_tick("sz000070", last=10.26, open_px=10., high=10.3, low=10., prev_close=10.,
                       last_ts="2026-10-15 09:30:03", source="sina_batch")
        sent = observer.call_args.args[1]
        self.assertEqual((sent["open"], sent["high"], sent["low"]), (10., 10.3, 10.))
        self.assertTrue(sent["_source_time_verified"])

    def test_older_source_quote_cannot_rollback_execution_or_emit_a_false_trigger(self):
        from unittest.mock import Mock
        hub = QuoteHub()
        observer = Mock()
        hub.on_quote = observer
        hub.apply_tick("sz000070", last=10.2, open_px=10., high=10.3, low=10., prev_close=10.,
                       last_ts="2026-10-15 09:30:03", source="sina_batch")
        hub.apply_tick("sz000070", last=10.8, open_px=10., high=10.8, low=10., prev_close=10.,
                       last_ts="2026-10-15 09:30:01", source="sina_batch")
        self.assertEqual(observer.call_count, 1)
        self.assertEqual(hub.get_execution_quote("sz000070")["last"], 10.2)


if __name__ == "__main__":
    unittest.main()


class TestTencentFallback(unittest.TestCase):
    def test_fallback_preserves_source_timestamp_and_ohlc(self):
        from unittest.mock import Mock, patch
        from quote_feed import fetch_tencent_batch
        fields = ["0"] * 35
        for i, value in {3:"12.96",4:"13.50",5:"13.30",30:"20261026143951",33:"13.46",34:"12.85"}.items():
            fields[i] = value
        response = Mock(content=('v_sz000070="'+'~'.join(fields)+'";').encode('gbk'))
        with patch('quote_feed._quote_http_get', return_value=response):
            spot = fetch_tencent_batch(['sz000070'])['sz000070']
        self.assertEqual(spot['last_ts'], '2026-10-26 14:39:51')
        self.assertEqual((spot['open'],spot['high'],spot['low']), (13.3,13.46,12.85))
        self.assertEqual(spot['_quote_source'], 'tencent_batch')
        fields[30] = ''
        response.content = ('v_sz000070="'+'~'.join(fields)+'";').encode('gbk')
        with patch('quote_feed._quote_http_get', return_value=response):
            self.assertEqual(fetch_tencent_batch(['sz000070']), {})
