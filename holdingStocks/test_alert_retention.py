from copy import deepcopy
from datetime import datetime

import unittest
from unittest.mock import patch

from alert_retention import AlertRetention, retention_session
from watch_snapshot import filter_portfolio_holdings


def test_calendar_boundary():
    for stamp in ('2026-10-16T16:00', '2026-10-17T12:00', '2026-10-19T08:59:59'):
        assert retention_session(datetime.fromisoformat(stamp)) == '2026-10-16'
    assert retention_session(datetime(2026, 10, 19, 9)) == '2026-10-19'
    assert retention_session(datetime(2026, 10, 8, 8, 59)) == '2026-09-30'


def signal():
    return dict(代码='600000', 名称='测试', 交易日='2026-10-16', 持仓=0,
                预警='已触买·槽满', 已触买='是', 过门OK=True, 信号时间='10:03', 买点=10)


def test_restart_missing_rows_and_expiry():
    database = {}
    def write(records):
        database.clear()
        database.update(deepcopy(records))
    first = AlertRetention(lambda: deepcopy(database), write)
    first.merge([signal()], datetime(2026, 10, 16, 15))
    restarted = AlertRetention(lambda: deepcopy(database), write)
    rows = restarted.merge([], datetime(2026, 10, 19, 8, 59))
    assert rows[0]['信号时间'] == '10:03'
    with patch('stock_names.resolve_stock_name', return_value='测试'):
        assert filter_portfolio_holdings(rows, portfolio_codes=set(), strategy_codes=set(), phase='preopen')
    assert restarted.merge([], datetime(2026, 10, 19, 9)) == []
    assert database == {}


def test_transient_signal_and_no_execution_fields():
    cache = AlertRetention()
    cache.merge([signal()], datetime(2026, 10, 16, 10))
    row = dict(代码='600000', 交易日='2026-10-16', 持仓=0, 预警='空仓', 过门OK=False, 可执行=False)
    cache.merge([row], datetime(2026, 10, 16, 16))
    assert row['已触买'] == '是'
    assert row['可执行'] is False


def test_failed_write_retried():
    calls = []
    def write(records):
        calls.append(deepcopy(records))
        if len(calls) == 1:
            raise RuntimeError('offline')
    cache = AlertRetention(write=write)
    with unittest.TestCase().assertRaises(RuntimeError):
        cache.merge([signal()], datetime(2026, 10, 16, 10))
    cache.merge([], datetime(2026, 10, 16, 11))
    assert len(calls) == 2
    assert not cache.dirty


def test_strategy_buy_status_delayed_until_next_session_nine():
    database = {}
    def write(records):
        database.clear()
        database.update(deepcopy(records))
    cache = AlertRetention(lambda: deepcopy(database), write)
    def held(day):
        return dict(代码='600000', 交易日=day, 持仓=100, 策略状态='策略持有',
                    策略入场时间='2026-10-16 10:03:00', 已触买='否')
    bought = held('2026-10-16')
    cache.merge([bought], datetime(2026, 10, 16, 10, 4))
    assert bought['策略展示状态'] == '已触买'
    assert bought['策略状态'] == '策略持有'
    assert bought['持仓'] == 100
    restarted = AlertRetention(lambda: deepcopy(database), write)
    before = held('2026-10-19')
    restarted.merge([before], datetime(2026, 10, 19, 8, 59))
    assert before['策略展示状态'] == '已触买'
    before = held('2026-10-19')
    restarted.merge([before], datetime(2026, 10, 19, 9))
    assert '策略展示状态' not in before
    assert before['策略状态'] == '策略持有'
    assert database == {}


def test_first_buy_time_survives_refresh_and_restart():
    stored = {}
    def write(records):
        stored.clear()
        stored.update(deepcopy(records))
    cache = AlertRetention(lambda: deepcopy(stored), write)
    first = signal()
    first['买信号时间'] = '09:35:01'
    cache.merge([first], datetime(2026, 10, 16, 10))
    later = signal()
    later['买信号时间'] = '10:40:00'
    cache.merge([later], datetime(2026, 10, 16, 11))
    assert later['首次触买时间'] == '09:35:01'
    restored = AlertRetention(lambda: deepcopy(stored), write).merge([], datetime(2026, 10, 17, 12))
    assert restored[0]['首次触买时间'] == '09:35:01'


if __name__ == '__main__':
    suite = unittest.TestSuite(unittest.FunctionTestCase(test) for name, test in list(globals().items())
                               if name.startswith('test_'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
