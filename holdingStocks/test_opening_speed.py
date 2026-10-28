"""Deterministic opening-session regressions, with no live quotes or account writes."""
import threading
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from opening_speed import opening_fast, quote_poll_interval, view_interval


class OpeningSpeedTests(unittest.TestCase):
    def test_window_boundaries_and_weekend(self):
        for clock, expected in [('09:24:59',False),('09:25:00',True),('09:30:00',True),('09:39:59',True),('09:40:00',False)]:
            now = datetime.fromisoformat('2026-10-27 '+clock)
            self.assertEqual(opening_fast(now), expected)
            self.assertEqual(quote_poll_interval(now=now), .25 if expected else 1.)
            self.assertEqual(view_interval(now), .1 if expected else .4)
        self.assertFalse(opening_fast(datetime(2026,10,31,9,30)))

    def test_slow_primary_cannot_delay_opening_backup(self):
        from quote_feed import QuoteHub, SinaBatchPoller
        stop, release, started, received = (threading.Event() for _ in range(4))
        hub = QuoteHub()
        hub.on_quote = lambda *_: received.set()
        def primary(*args, **kwargs):
            started.set(); release.wait(3); return {}
        def backup(codes, **kwargs):
            stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            return {codes[0]:dict(last=10.3,open=10.,high=10.3,low=10.,prev_close=10.,last_ts=stamp)}
        poller = SinaBatchPoller(hub, ['sz000070'], stop=stop)
        with patch('quote_feed.fetch_sina_batch', side_effect=primary), \
             patch('quote_feed.fetch_tencent_batch', side_effect=backup), \
             patch('opening_speed.opening_fast', return_value=True), \
             patch('watch_config.market_phase', return_value='continuous'):
            worker = threading.Thread(target=poller._run_group, args=(['sz000070'],), daemon=True)
            worker.start()
            try:
                self.assertTrue(started.wait(1))
                self.assertTrue(received.wait(.5), 'backup waited for the blocked primary')
                self.assertFalse(release.is_set())
            finally:
                stop.set(); release.set(); worker.join(3)
        self.assertFalse(worker.is_alive())

    def test_pooled_http_reuses_connection_session(self):
        from quote_feed import _quote_http_get
        local = threading.local()
        with patch('quote_feed._QUOTE_HTTP', local), patch('quote_feed.requests.Session') as session:
            _quote_http_get('https://example.invalid/one', timeout=1)
            _quote_http_get('https://example.invalid/two', timeout=1)
            session.assert_called_once()
            self.assertEqual(session.return_value.get.call_count, 2)

    def test_single_stock_audit_returns_backup_before_primary_timeout(self):
        from quote_feed import fetch_open_audit_quote
        release = threading.Event()
        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        spot=dict(last=10.3,open=10.,high=10.3,low=10.,prev_close=10.,last_ts=stamp)
        def primary(*args, **kwargs):
            release.wait(3); return {}
        try:
            with patch('quote_feed.fetch_sina_batch', side_effect=primary), \
                 patch('quote_feed.fetch_tencent_batch', return_value={'sz000070':spot}):
                result = fetch_open_audit_quote('sz000070')
            self.assertEqual(result['_quote_source'], 'tencent_batch')
            self.assertFalse(release.is_set())
        finally:
            release.set()
