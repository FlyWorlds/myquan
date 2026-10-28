import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock

from quote_resilience import SourceRouter

NOW = datetime(2026, 10, 26, 10, 0)


def quote(age=0):
    return dict(last=10.2, open=10., high=10.3, low=9.9, prev_close=10.,
                last_ts=(NOW-timedelta(seconds=age)).strftime('%Y-%m-%d %H:%M:%S'))


class TestFailover(unittest.TestCase):
    def test_primary_timeout_trips_and_recovers_without_delaying_backup(self):
        clock = [0.]
        primary = Mock(side_effect=TimeoutError)
        backup = Mock(return_value={'sz000070': quote()})
        router = SourceRouter([('sina_batch', primary), ('tencent_batch', backup)], clock=lambda: clock[0])
        for _ in range(4):
            result = router.fetch(['sz000070'], now=NOW, continuous=True)
            self.assertEqual(result['sz000070']['_quote_source'], 'tencent_batch')
        self.assertEqual(primary.call_count, 3)
        self.assertEqual(router.status()['sina_batch']['circuit'], 'open')
        clock[0] = 31
        primary.side_effect = None
        primary.return_value = {'sz000070': quote()}
        result = router.fetch(['sz000070'], now=NOW, continuous=True)
        self.assertEqual(result['sz000070']['_quote_source'], 'sina_batch')
        self.assertEqual(backup.call_count, 4)
        self.assertEqual(router.status()['sina_batch']['failures'], 0)

    def test_only_missing_and_stale_symbols_are_repaired(self):
        backup = Mock(return_value={'sz000002': quote(), 'sz000003': quote()})
        router = SourceRouter([('sina_batch', Mock(return_value={
            'sz000001': quote(), 'sz000002': quote(90)})), ('tencent_batch', backup)])
        result = router.fetch(['sz000001', 'sz000002', 'sz000003'], now=NOW, continuous=True)
        self.assertEqual(backup.call_args.args[0], ['sz000002', 'sz000003'])
        self.assertEqual(len(result), 3)

    def test_both_sources_stale_return_no_executable_quote(self):
        router = SourceRouter([('sina_batch', Mock(return_value={'sz000001': quote(90)})),
                               ('tencent_batch', Mock(return_value={'sz000001': quote(90)}))])
        self.assertEqual(router.fetch(['sz000001'], now=NOW, continuous=True), {})
        # The exchange clock naturally stops during lunch and after the close.
        self.assertIn('sz000001', router.fetch(['sz000001'], now=NOW, continuous=False))

    def test_stale_auction_response_does_not_circuit_break_the_opening_tick(self):
        source = Mock(return_value={'sz000001': quote(300)})
        router = SourceRouter([('sina_batch', source)])
        for _ in range(5):
            self.assertEqual(router.fetch(['sz000001'], now=NOW, continuous=True), {})
        self.assertEqual(source.call_count, 5)
        self.assertEqual(router.status()['sina_batch']['circuit'], 'closed')
        source.return_value = {'sz000001': quote()}
        self.assertIn('sz000001', router.fetch(['sz000001'], now=NOW, continuous=True))

    def test_invalid_prices_future_time_and_unknown_symbols_are_rejected(self):
        bad = quote(); bad['last'] = float('inf')
        router = SourceRouter([('sina_batch', Mock(return_value={
            'sz000001': bad, 'sz000002': quote(-90), 'sz999999': quote()}))])
        self.assertEqual(router.fetch(['sz000001', 'sz000002'], now=NOW, continuous=True), {})
