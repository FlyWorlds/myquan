import pandas as pd
import pytest
from strategy.strategies.strategy3 import intraday_scan as live
from strategy.strategies.strategy3 import manual_scan as scan


def history():
    return pd.DataFrame(dict(date=pd.bdate_range(end='2026-10-22',periods=120),open=10.,high=10.2,low=9.8,close=10.,volume=1000.,symbol='sh600000'))


def quote(clock='09:25:00',received='09:25:01',**extra):
    return dict(last_ts=f'2026-10-23 {clock}',received_at=f'2026-10-23 {received}+08:00',
                source_time_verified=True,raw_open=9.,raw_last=9.2,raw_high=9.5,raw_low=8.8,prev_close=10.,volume=100000.,**extra)


def context(clock='09:25:00'):
    return live.scan_context(f'2026-10-23 {clock}+08:00')


def test_session_gates_and_holiday_history():
    assert context('09:24:59')['mode']=='daily'
    assert context()['mode']=='intraday'
    assert context('15:14:59')['history_as_of']=='2026-10-22'
    assert context('15:15:00')['mode']=='daily'
    assert live.scan_context('2026-10-26 09:25')['history_as_of']=='2026-10-23'
    assert live.scan_context('2026-10-08 09:25')['history_as_of']=='2026-09-30'
    assert live.scan_context('2026-10-01 09:25')['mode']=='daily'


def test_925_uses_final_open_without_intraday_or_future_ohlc():
    q=quote();q.update(raw_last=0,raw_high=0,raw_low=0,volume=0)
    frame,meta=live.live_daily(history(),q,context())
    assert frame.iloc[-1][['open','high','low','close']].tolist()==[9.]*4
    assert frame.iloc[-1].volume==0 and meta['price_basis']=='auction_open'
    assert history().shape[0]==120 and len(frame)==121


def test_latest_price_and_volume_units_and_history_scale():
    q=quote('10:00:00','10:00:01');q.update(prev_close=5.,raw_open=4.5,raw_last=4.7,raw_high=4.8,raw_low=4.4)
    frame,meta=live.live_daily(history(),q,context('10:00:00'))
    assert frame.iloc[-2].close==5. and frame.iloc[-1].close==4.7
    assert frame.iloc[-1].volume==1000 and meta['price_basis']=='live_last'
    assert frame.iloc[-1].low==4.4


@pytest.mark.parametrize('change,status',[
    ({'last_ts':'2026-10-22 15:00:00'},'stale_quote'),
    ({'last_ts':'2026-10-23 10:00:02'},'future_quote'),
    ({'last_ts':'2026-10-23 09:24:59'},'unconfirmed_quote'),
    ({'last_ts':'2026-10-23 09:50:00'},'stale_quote'),
    ({'source_time_verified':False},'unconfirmed_quote'),
    ({'raw_open':0},'invalid_quote'),
    ({'raw_last':0},'invalid_quote'),
    ({'raw_high':0},'invalid_quote'),
])
def test_invalid_quotes_never_become_current_observations(change,status):
    q=quote('10:00:00','10:00:01');q.update(change)
    with pytest.raises(live.QuoteUnavailable) as exc:live.live_daily(history(),q,context('10:00:00'))
    assert exc.value.status==status


def test_lunch_accepts_last_morning_quote_and_open_does_not_reuse_auction():
    live.live_daily(history(),quote('11:30:00','12:00:00'),context('12:00:00'))
    with pytest.raises(live.QuoteUnavailable):live.live_daily(history(),quote('09:25:00','09:30:01'),context('09:30:00'))


def test_missing_history_or_quote_does_not_use_previous_close():
    with pytest.raises(live.QuoteUnavailable):live.live_daily(history(),None,context())
    with pytest.raises(live.QuoteUnavailable):live.live_daily(history().iloc[:-1],quote(),context())


def test_snapshot_validity_changes_at_925_and_close():
    old=dict(as_of='2026-10-22',config_hash='x')
    assert live.snapshot_valid(old,'x','2026-10-23 09:24:00')
    assert not live.snapshot_valid(old,'x','2026-10-23 09:25:00')
    current=dict(as_of='2026-10-23',scan_mode='intraday',config_hash='x')
    assert live.snapshot_valid(current,'x','2026-10-23 09:25:00')
    assert not live.snapshot_valid(current,'x','2026-10-23 15:15:00')
    assert not live.snapshot_valid(current,'new','2026-10-23 10:00:00')


def test_scan_uses_current_price_for_panic_and_separate_feature_cache(tmp_path,monkeypatch):
    monkeypatch.setattr(scan,'OUT',tmp_path)
    monkeypatch.setattr(scan,'load_daily',lambda symbol:(history(),{}))
    seen=[]
    def evaluate(symbol,name,day,cfg,feature_dir,**kwargs):
        seen.append(feature_dir)
        row=dict(broken=True,close=kwargs['daily'].iloc[-1].close,anchor=9.3)
        return dict(status='ready',broken=True,candidate=True),pd.DataFrame([row])
    monkeypatch.setattr(scan,'_one',evaluate)
    item=dict(symbol='sh600000',name='test')
    q=quote('10:00:00','10:00:01')
    a=scan._scan_stock(item,'2026-10-23',{},context('10:00:00'),q)
    q.update(raw_last=9.4)
    b=scan._scan_stock(item,'2026-10-23',{},context('10:00:00'),q)
    assert a['warning'] and not b['warning']  # 同日low未变；收复前低不继续计入盘中预警。
    assert all(p==tmp_path/'intraday_features' for p in seen)
    assert a['quote_at'].startswith('2026-10-23T10:00:00')


def test_run_freezes_quotes_and_publishes_live_denominator(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(scan,'OUT',tmp_path)
    monkeypatch.setattr(scan,'_pool',lambda workers:ThreadPoolExecutor(max_workers=workers))
    items=[dict(symbol='sh600000',code='600000',name='a'),dict(symbol='sz000001',code='000001',name='b')]
    monkeypatch.setattr(scan,'universe',lambda:(items,{}))
    monkeypatch.setattr(scan,'scan_context',context)
    q=quote(); calls=[]
    def fetch(symbols):
        calls.append(symbols)
        return {'sh600000':q}
    monkeypatch.setattr(scan,'fetch_scan_quotes',fetch)
    def evaluate(it,as_of,cfg,ctx,live_quote):
        assert ctx['mode']=='intraday' and as_of=='2026-10-23'
        return dict(**it,status='ready' if live_quote else 'missing_quote',warning=bool(live_quote),candidate=False,quote_at=live_quote['last_ts'] if live_quote else None)
    monkeypatch.setattr(scan,'_scan_stock',evaluate)
    scan.run()
    snap=scan.read_json(tmp_path/'snapshot.json',{})
    assert calls==[['sh600000','sz000001']]
    assert snap['scan_mode']=='intraday' and snap['history_as_of']=='2026-10-22'
    assert snap['scanned_count']==1 and snap['warning_count']==1
    assert snap['counts']['missing_quote']==1 and scan.status()['state']=='done'


def test_quote_parser_preserves_raw_auction_and_real_timestamp(monkeypatch):
    from holdingStocks import quote_feed
    class Response:
        parts=['0']*32
        parts[0]='test'; parts[1]='9';parts[2]='10';parts[8]='20000'
        parts[30]='2026-10-23';parts[31]='09:25:00'
        content=('var hq_str_sh600000="'+','.join(parts)+'";').encode('gbk')
    monkeypatch.setattr(quote_feed.requests,'get',lambda *a,**k:Response())
    raw=quote_feed.fetch_sina_batch(['sh600000'])['sh600000']
    assert raw['source_time_verified'] and raw['raw_last']==0
    assert raw['raw_open']==9 and raw['volume']==20000
    raw['received_at']='2026-10-23 09:25:01+08:00'
    f,meta=live.live_daily(history(),raw,context())
    assert f.iloc[-1].close==9 and f.iloc[-1].volume==200
    assert meta['price_basis']=='auction_open'
