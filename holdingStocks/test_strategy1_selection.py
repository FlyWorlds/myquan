import json
from unittest.mock import patch
import pytest
from holdingStocks import strategy1_selection as service

@pytest.fixture
def files(tmp_path, monkeypatch):
    active = tmp_path/'pool.json'
    active.write_text(json.dumps({'picks': [{'code': '600001'}]}))
    monkeypatch.setattr(service, 'ACTIVE', active)
    monkeypatch.setattr(service, 'STATE', tmp_path/'state')
    monkeypatch.setattr(service, '_running', False)
    monkeypatch.setattr(service, '_error', None)
    return active


def draft():
    return dict(id='test', base=service.fingerprint(), indices=['沪深300'], as_of='2026-11-07', period='test',
                picks=[dict(code=f'600{i:03}', name=str(i), thr=.025) for i in range(30)])


def test_start_does_not_change_live_pool_and_reserves_job(files):
    before = files.read_bytes()
    with patch.object(service.threading, 'Thread') as thread:
        assert service.start(['沪深300'])['running']
        with pytest.raises(ValueError, match='正在运行'):
            service.start(['中证500'])
        thread.assert_called_once()
    assert files.read_bytes() == before


def test_save_activates_30_with_atomic_thresholds(files, monkeypatch):
    d = draft(); service.write(service.STATE/'draft.json', d)
    result = service.save('test')
    assert result['draft']['saved_at']
    payload=json.loads(files.read_text())
    assert len(payload['picks']) == 30
    from strategy import watch_universe
    monkeypatch.setattr(watch_universe, 'STRATEGY1_PICKS_PATH', files)
    assert len(watch_universe.load_strategy1_thr_map()) == 30
    assert service.save('test')['draft']['saved_at']


def test_save_rejects_outdated_or_short_draft(files):
    d=draft(); service.write(service.STATE/'draft.json', d)
    files.write_text('{"picks": []}')
    with pytest.raises(ValueError, match='其他操作'):
        service.save('test')
    d['base']=service.fingerprint();d['picks']=d['picks'][:29]
    service.write(service.STATE/'draft.json',d)
    with pytest.raises(ValueError, match='30只'):
        service.save('test')


def test_invalid_scope_does_not_start(files):
    for scope in ([], ['不存在'], None, '沪深300'):
        with pytest.raises(ValueError):
            service.start(scope)


def test_saved_pool_does_not_append_fixed_stock(files, monkeypatch):
    d=draft();service.write(service.STATE/'draft.json',d);service.save('test')
    from holdingStocks import watch_config
    monkeypatch.setattr(watch_config, 'load_strategy1_payload', lambda: json.loads(files.read_text()))
    monkeypatch.setattr(watch_config, 'load_strategy1_thr_map', lambda: {p['code']: p['thr'] for p in d['picks']})
    monkeypatch.setattr(watch_config, 'merge_self_watchlist', lambda rows,*a,**kw: rows)
    rows=watch_config.strategy1_watchlist()
    assert len(rows)==30
    assert '603138' not in {r['code'] for r in rows}


def test_four_index_choices_filter_actual_membership():
    import pandas as pd
    rows=[dict(code=f'60000{i}',symbol=f'sh60000{i}',name='正常股票',index=name) for i,name in enumerate(service.INDICES)]
    meta=pd.DataFrame(rows + [rows[0],dict(code='300001',symbol='sz300001',name='创业板',index='沪深300'),dict(code='600999',symbol='sh600999',name='ST股票',index='沪深300')])
    for i,name in enumerate(service.INDICES):
        assert service.filter_universe(meta,[name]).code.tolist()==[f'60000{i}']
    assert len(service.filter_universe(meta,service.INDICES))==4


def test_save_http_endpoint_uses_server_draft(files):
    import sys
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).parent))
    from transport.http import build_watch_request_handler
    service.write(service.STATE/'draft.json',draft())
    handler=build_watch_request_handler(root=files.parent,watch_meta_file=files.parent/'snapshot.json',
        watch_ui_dist=files.parent,ws_hub=None,snap_lock=threading.Lock(),get_last_snapshot=lambda: {},
        get_strategies_api=lambda: {},get_factors_api=lambda: {},handle_sectors_api=lambda path: (200,{}),
        watch_ui_dist_ready=lambda: False)
    server=ThreadingHTTPServer(('127.0.0.1',0),handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        request=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/strategy1/selection/save',
            data=b'{"draft_id":"test"}',headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=5) as response:
            result=json.load(response)
        assert result['active']['selection_id']=='test'
        assert len(result['active']['picks'])==30
    finally:
        server.shutdown();server.server_close()
