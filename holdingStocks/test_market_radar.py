import copy
import json
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import market_radar as radar


class MarketRadarTests(unittest.TestCase):
    def stock(self, **changes):
        return dict(dict(code='600330', name='测试', price=10, pct=10, industry='电子',
            float_cap_yi=50, seal_fund_yi=1, limit_days=2, break_times=0,
            first_seal='09:35:00'), **changes)

    def test_pool_scaling_missingness_and_dedup(self):
        raw = dict(c='600330', n='测试', p=10000, fund=100000000, ltsz=5000000000,
            fbt=93500, zdp=10, zbc=0)
        rows = radar.normalize_pool([raw, raw, dict(c='invalid')])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['price'], 10)
        self.assertEqual(rows[0]['first_seal'], '09:35:00')
        self.assertEqual(rows[0]['seal_fund_yi'], 1)
        self.assertIsNone(rows[0]['turnover'])
        self.assertIsNone(radar.clock(None))
        self.assertIsNone(radar.clock(0))
        self.assertIsNone(radar.clock(996699))

    def test_themes_count_unique_members_and_stay_separate_from_industry(self):
        pools = dict(sealed=[self.stock(), self.stock(), self.stock(code='000070')], broken=[], down=[])
        reasons = [dict(code='600330', reason='机器人+机器人+电子'), dict(code='000070', reason='机器人+AI')]
        original = copy.deepcopy(pools)
        data = radar.derive(pools, reasons)
        self.assertEqual(data['themes'][0]['name'], '机器人')
        self.assertEqual(data['themes'][0]['count'], 2)
        self.assertEqual(data['industries'][0]['count'], 2)
        self.assertEqual(data['summary']['sealed'], 2)
        self.assertEqual(pools, original)
        self.assertEqual(data['stocks'][0]['grade'], 'A')

    def test_unavailable_broken_pool_is_unknown_not_zero(self):
        data = radar.derive(dict(sealed=[self.stock()], broken=None, down=None), [])
        self.assertIsNone(data['summary']['broken'])
        self.assertIsNone(data['summary']['down'])
        self.assertIsNone(data['summary']['break_rate'])
        self.assertEqual(data['themes'], [])

    def test_failed_today_pool_never_fetches_reference_snapshot(self):
        def fetch(url):
            self.assertNotEqual(url, radar.REFERENCE)
            raise RuntimeError('offline')
        with patch.object(radar, 'fetch_text', side_effect=fetch):
            with self.assertRaises(RuntimeError):
                radar.collect_eastmoney()

    def test_provider_yesterday_date_is_rejected(self):
        with patch.object(radar, 'fetch_text', return_value=json.dumps(dict(data=dict(qdate=20261021, pool=[])))):
            with self.assertRaises(RuntimeError):
                radar.collect_eastmoney()

    def test_current_successful_empty_pool_does_not_fallback_to_yesterday(self):
        def fetch(url):
            self.assertNotEqual(url, radar.REFERENCE)
            return json.dumps(dict(data={'info': []} if '10jqka' in url else {'pool': []}))
        with patch.object(radar, 'fetch_text', side_effect=fetch):
            result = radar.collect_eastmoney()
        self.assertEqual(result['mode'], 'provider')
        self.assertEqual(result['summary']['sealed'], 0)

    def cls_row(self, **changes):
        return dict(dict(secu_code='sz002123', secu_name='测试', change=.1, last_px=11,
            time='2026-10-22 10:01:02', num_stocks=1, limit_up_days=2,
            up_reason='机器人+芯片|公司详细业务说明'), **changes)

    def test_cls_today_units_reasons_and_no_fabricated_fields(self):
        body = json.dumps(dict(code=200, data=[self.cls_row()]))
        with patch.object(radar, 'now', return_value=datetime(2026,10,22,11,tzinfo=ZoneInfo('Asia/Shanghai'))), patch.object(radar, 'fetch_text', return_value=body):
            value = radar.collect_cls()
        stock = value['stocks'][0]
        self.assertEqual(stock['price'], 11)
        self.assertEqual(stock['pct'], 10)
        self.assertEqual(stock['themes'], ['机器人', '芯片'])
        self.assertEqual(stock['reason_detail'], '公司详细业务说明')
        self.assertEqual(value['broken'][0]['reason_detail'], '公司详细业务说明')
        self.assertEqual(stock['quote_at'], '2026-10-22 10:01:02')
        for key in ['score', 'seal_fund_yi', 'first_seal', 'break_times']:
            self.assertIsNone(stock[key])
        self.assertIsNone(value['themes'][0]['seal_fund_yi'])
        self.assertIsNone(value['summary']['grade_a'])

    def test_cls_rejects_yesterday_incomplete_and_undated_empty(self):
        bad_rows = [[self.cls_row(time='2026-10-21 10:01:02')], [self.cls_row(num_stocks=2)], []]
        for rows in bad_rows:
            with patch.object(radar, 'now', return_value=datetime(2026,10,22,11,tzinfo=ZoneInfo('Asia/Shanghai'))), patch.object(radar, 'fetch_text', return_value=json.dumps(dict(code=200, data=rows))):
                with self.assertRaises(RuntimeError):
                    radar.collect_cls()

    def test_cls_success_does_not_wait_for_failed_eastmoney(self):
        with patch.object(radar, 'collect_cls', return_value={'source': 'cls'}), patch.object(radar, 'collect_eastmoney') as backup:
            self.assertEqual(radar.collect()['source'], 'cls')
            backup.assert_not_called()

    def test_today_expired_or_failed_pool_is_not_exposed(self):
        current = datetime(2026,10,22,10,tzinfo=ZoneInfo('Asia/Shanghai'))
        for stamp, failure in [('2026-10-22 09:59:00', None), ('2026-10-22 10:00:00', 'offline')]:
            with patch.object(radar.CACHE.__class__, 'read_text', side_effect=OSError):
                service = radar.RadarService()
            service.data = dict(version=1, mode='provider', trade_date='2026-10-22', fetched_at=stamp, stocks=[self.stock()], summary={'sealed': 1})
            service.error = failure
            service.busy = True
            with patch.object(radar, 'now', return_value=current):
                result = service.get()
            self.assertEqual(result['stocks'], [])
            self.assertNotIn('summary', result)
            self.assertEqual(result['status'], 'unavailable')

    def test_old_snapshot_is_marked_historical_and_singleflight_is_nonblocking(self):
        with patch.object(radar.CACHE.__class__, 'read_text', side_effect=OSError):
            service = radar.RadarService()
        service.data = dict(version=1, trade_date='2026-10-21', fetched_at='2026-10-21 18:31:12', stocks=[])
        with patch.object(radar, 'now', return_value=datetime(2026,10,22,10,tzinfo=ZoneInfo('Asia/Shanghai'))), patch.object(radar.threading, 'Thread') as thread:
            first = service.get()
            second = service.get(force=True)
        self.assertEqual(first['status'], 'unavailable')
        self.assertEqual(first['stocks'], [])
        self.assertNotIn('summary', first)
        self.assertTrue(first['stale'])
        self.assertTrue(second['refreshing'])
        thread.assert_called_once()


if __name__ == '__main__':
    unittest.main()
