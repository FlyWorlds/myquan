import pandas as pd
from strategy.strategies.strategy3 import manual_scan as m


def test_exact_index_filter_does_not_union_other_universe():
    d=pd.DataFrame({'成份券代码Constituent Code':[600000,600001,688001,300001,830001,2001],
                    '成份券名称Constituent Name':['浦发','ST测试','科创','创业','北交','正常']})
    rows,n=m.parse_constituents(d,{'002001':'*ST最新'})
    assert [x['code'] for x in rows]==['600000'] and n==5


def test_empty_initial_pool_has_no_fallback():
    s=m.empty_snapshot()
    assert s['scope']==m.SCOPE and not s['rows'] and not s['picks']


def test_warning_does_not_require_entry_and_mark_requires_warning():
    assert m.classify({'broken':True,'candidate':False})==(True,False)
    assert m.classify({'broken':True,'candidate':True})==(True,True)
    assert m.classify({'status':'stale','candidate':True})==(False,False)


def test_get_status_does_not_start_scan(tmp_path,monkeypatch):
    monkeypatch.setattr(m,'OUT',tmp_path)
    assert m.status()['state']=='idle'
    assert not list(tmp_path.iterdir())


def test_double_click_does_not_spawn_second_job(tmp_path,monkeypatch):
    monkeypatch.setattr(m,'OUT',tmp_path);calls=[]
    monkeypatch.setattr(m.subprocess,'Popen',lambda *a,**k:calls.append(a))
    m.start();m.start()
    assert len(calls)==1
    assert m.read_json(tmp_path/'snapshot.json',{})['rows']==[]


def test_manual_job_publishes_warning_and_badge_without_old_pool(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(m,'OUT',tmp_path)
    monkeypatch.setattr(m,'_pool',lambda workers:ThreadPoolExecutor(max_workers=workers))
    monkeypatch.setattr(m,'scan_context',lambda:dict(mode='daily',as_of='2026-10-22',history_as_of='2026-10-22',started_at='2026-10-22T16:00:00+08:00'))
    items=[dict(symbol='sh600000',code='600000',name='甲'),dict(symbol='sz000001',code='000001',name='乙')]
    monkeypatch.setattr(m,'universe',lambda:(items,{'index':'000852'}))
    monkeypatch.setattr(m,'_scan_stock',lambda it,*args:dict(**it,status='ready',broken=True,warning=True,candidate=it['code']=='000001'))
    m.run()
    snap=m.read_json(tmp_path/'snapshot.json',{})
    assert snap['warning_count']==2 and snap['candidate_count']==1
    assert len(snap['picks'])==2 and m.status()['state']=='done'


def test_http_get_is_readonly_and_post_requires_local_origin(tmp_path,monkeypatch):
    import sys,types,threading,json,http.client
    from http.server import ThreadingHTTPServer
    sys.path.insert(0,str(m.ROOT/'holdingStocks'))
    from transport.http import build_watch_request_handler
    calls=[]
    monkeypatch.setattr(m,'status',lambda:dict(state='idle'))
    monkeypatch.setattr(m,'start',lambda:calls.append('start') or dict(state='starting'))
    monkeypatch.setitem(sys.modules,'strategy3_watch',types.SimpleNamespace(build_strategy3_payload=lambda:dict(rows=[])))
    handler=build_watch_request_handler(root=tmp_path,watch_meta_file=tmp_path/'meta.json',watch_ui_dist=tmp_path,
        ws_hub=None,snap_lock=None,get_last_snapshot=lambda:{},get_strategies_api=lambda:{},get_factors_api=lambda:{},
        handle_sectors_api=lambda x:(200,{}),watch_ui_dist_ready=lambda:False)
    server=ThreadingHTTPServer(('127.0.0.1',0),handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
        conn.request('GET','/api/strategy3/scan');r=conn.getresponse();data=json.loads(r.read())
        assert r.status==200 and data['payload']['rows']==[] and not calls
        conn.request('POST','/api/strategy3/scan',headers={'Origin':'https://untrusted.example'})
        r=conn.getresponse();r.read();assert r.status==403 and not calls
        conn.request('POST','/api/strategy3/scan');r=conn.getresponse();r.read()
        assert r.status==202 and calls==['start']
        conn.close()
    finally:server.shutdown();server.server_close();thread.join()


def test_default_replay_cannot_fall_back_to_archived_80_stock_pool(tmp_path,monkeypatch):
    import pytest
    from strategy.strategies.strategy3.bound_backtest import run_bound
    monkeypatch.setattr(m,'OUT',tmp_path)
    m.write_json(tmp_path/'snapshot.json',m.empty_snapshot())
    with pytest.raises(ValueError,match='股票池为空'):run_bound()


def test_process_pool_uses_spawn_and_six_independent_workers(monkeypatch):
    options={}
    monkeypatch.setattr(m,'ProcessPoolExecutor',lambda **kw:options.update(kw) or options)
    m._pool(m.WORKERS)
    assert options['max_workers']==6
    assert options['mp_context'].get_start_method()=='spawn'


def test_complete_cache_skips_remote_refresh_but_stale_cache_refreshes(tmp_path,monkeypatch):
    from strategy import data
    calls=[]
    days=pd.bdate_range(end='2026-10-22',periods=120)
    daily=pd.DataFrame({'date':days})
    monkeypatch.setattr(m,'load_daily',lambda s:(daily,{}))
    monkeypatch.setattr(data,'fetch_daily',lambda *a,**k:calls.append(a))
    monkeypatch.setattr(m,'_one',lambda *a,**k:({'status':'ready','broken':True,'candidate':False},None))
    item=dict(symbol='sh600000',name='浦发')
    assert m._scan_stock(item,'2026-10-22',{})['used_daily_cache'] and not calls
    assert not m._scan_stock(item,'2026-10-23',{})['used_daily_cache'] and len(calls)==1
