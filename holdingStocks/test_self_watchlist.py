from __future__ import annotations

import copy
from datetime import datetime
from unittest.mock import patch

import pytest

from self_watchlist import SelfWatchlist


class MemoryStore:
    def __init__(self):
        self.revision, self.data = 0, None
        self.installed = None
        self.changes = 0
    def read(self, key):
        return self.revision, copy.deepcopy(self.data)
    def write(self, key, data, revision):
        assert revision == self.revision
        self.data = copy.deepcopy(data)
        self.revision += 1
        return self.revision
    def install(self, data):
        self.installed = copy.deepcopy(data)
    def changed(self):
        self.changes += 1


def service():
    store = MemoryStore()
    quote = dict(name='测试股票', last=10, prev_close=9.8, day_chg_pct=2.04,
                 last_ts='2026-11-02 10:00:00')
    manager = SelfWatchlist(read=store.read, write=store.write, fetch=lambda sina: dict(quote),
        install=store.install, changed=store.changed, now=lambda: datetime(2026, 11, 2, 10, 0, 1))
    return manager, store, quote


def test_preview_is_read_only_and_confirmation_rechecks_quote_before_database_commit():
    manager, store, quote = service()
    result = manager.preview('sh600000')
    assert result['quote']['code'] == '600000'
    assert store.data is None and store.changes == 0
    quote['last'] = 10.1
    manager.confirm(result['token'])
    assert store.revision == 1 and store.changes == 1
    assert store.data['items'][-1]['code'] == '600000'
    assert store.data['items'][-1]['verifiedQuote']['price'] == 10.1
    assert manager.snapshot()['items'] == store.data['items']


def test_invalid_stale_missing_or_changed_identity_never_adds():
    for bad in ['bad', '000000', 'sh000001', '600000;rm', '../123456', '399001', 'bj920001']:
        manager, store, _ = service()
        with pytest.raises(ValueError): manager.preview(bad)
        assert store.data is None
    for value in [None, 0, float('nan')]:
        manager, store, quote = service()
        quote['last'] = value
        with pytest.raises(ValueError): manager.preview('600000')
        assert store.data is None
    manager, store, quote = service()
    pending = manager.preview('600000')
    quote['last_ts'] = '2026-10-30 15:00:00'
    with pytest.raises(ValueError): manager.confirm(pending['token'])
    assert store.data is None
    quote['last_ts'] = '2026-11-02 10:00:00'
    quote['name'] = '另一名称'
    with pytest.raises(ValueError): manager.confirm(pending['token'])
    assert store.data is None


def test_duplicates_remove_and_empty_pool_survive_reload_without_changing_paper_ledger():
    manager, store, _ = service()
    first = manager.preview('600000')
    manager.confirm(first['token'])
    assert manager.preview('600000')['alreadyAdded']
    manager.confirm(manager.preview('600000')['token'])
    assert store.revision == 1
    manager.remove('600000')
    assert store.data['removed']['600000'] == '2026-11-02'
    for item in manager.snapshot()['items']:
        manager.remove(item['code'])
    assert manager.snapshot()['items'] == []
    assert not any(key in store.data for key in ['holdings', 'trades', 'ledger'])


def test_expired_token_and_write_failure_do_not_install_or_report_success():
    manager, store, _ = service()
    pending = manager.preview('600000')
    manager.pending[pending['token']]['expires'] = 0
    with pytest.raises(ValueError): manager.confirm(pending['token'])
    pending = manager.preview('600000')
    with patch.object(manager, 'write', side_effect=RuntimeError('revision conflict')):
        with pytest.raises(RuntimeError): manager.confirm(pending['token'])
    assert store.installed is None and store.changes == 0


def test_runtime_pool_and_deleted_signal_scope_are_separate():
    import strategy.watch_universe as universe
    from watch_config import self_watch_items
    with patch.object(universe, '_RUNTIME_SELF_PICKS', None), patch.object(universe, '_RUNTIME_REMOVED', {}):
        universe.install_self_watchlist({'items': [{'code': '600000', 'name': '测试股票'}],
                                        'removed': {'600330': '2026-11-02'}})
        assert universe.self_watchlist_codes() == {'600000'}
        assert [r['code'] for r in self_watch_items({})] == ['600000']
        assert universe.removed_self_codes('2026-11-02') == {'600330'}
        assert universe.removed_self_codes('2026-11-03') == set()


def test_deleted_todays_signal_retains_original_time_but_is_display_only():
    from alert_retention import AlertRetention
    retention = AlertRetention(strategy_id='strategy1')
    row = dict(代码='600000', 名称='测试股票', 交易日='2026-11-02', 持仓=0,
        已触买='是', 预警='已触买', 买信号时间='2026-11-02 09:40:00', 信号策略ID='strategy1')
    now = datetime(2026, 11, 2, 10, 0)
    retention.merge([row], now=now, strategy_codes={'600000'})
    restored = retention.merge([], now=now, strategy_codes={'600000'})
    assert restored[0]['持仓'] == 0 and restored[0]['预警保留']
    assert restored[0]['买信号时间'] == '2026-11-02 09:40:00'
    assert retention.merge([], now=datetime(2026, 11, 3, 10), strategy_codes=set()) == []


def test_http_confirmation_flow_and_origin_checks(tmp_path):
    import json
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    from transport.http import build_watch_request_handler
    manager, store, _ = service()
    handler = build_watch_request_handler(root=tmp_path, watch_meta_file=tmp_path/'snapshot.json',
        watch_ui_dist=tmp_path/'dist', ws_hub=None, snap_lock=threading.Lock(),
        get_last_snapshot=lambda: None, get_strategies_api=lambda: {}, get_factors_api=lambda: {},
        handle_sectors_api=lambda path: (404, {}), watch_ui_dist_ready=lambda: False,
        self_watchlist=manager)
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}/api/self-watchlist'
    def call(path='', body=None, headers=None):
        req = Request(base+path, data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type': 'application/json', **(headers or {})})
        with urlopen(req, timeout=3) as response:
            return json.load(response)
    try:
        initial_len = len(call()['items'])
        preview = call('/preview', {'code': '600000'})
        assert store.data is None
        with pytest.raises(HTTPError) as exc:
            call('/confirm', {'token': preview['token']}, {'Origin': 'https://untrusted.example'})
        assert exc.value.code == 403 and store.data is None
        added = call('/confirm', {'token': preview['token']})
        assert added['ok'] and len(added['items']) == initial_len + 1
        removed = call('/remove', {'code': '600000'})
        assert removed['ok'] and len(removed['items']) == initial_len
        assert store.data['removed']['600000'] == '2026-11-02'
        with pytest.raises(HTTPError) as exc:
            call('/confirm', {'token': 'invented-token'})
        assert exc.value.code == 400
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_adding_live_quote_symbols_is_idempotent_without_restarting_original_feed():
    from quote_feed import QuoteFeedManager
    feed = QuoteFeedManager(['sh600330'], sse_sinas=[])
    with patch('quote_feed.SinaBatchPoller') as poller, patch('quote_feed.threading.Thread') as thread:
        feed.add_symbols(['sh600000', 'sh600000'])
        feed.add_symbols(['sh600000'])
        assert feed.sinas == ['sh600330', 'sh600000']
        assert feed.hub.expected_symbols == feed.sinas
        assert poller.call_count == 1 and thread.return_value.start.call_count == 1
