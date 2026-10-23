import pandas as pd
from strategy.strategies.strategy3 import market_scan as m


def test_market_universe_includes_names_outside_cached_and_strategy16(tmp_path,monkeypatch):
    monkeypatch.setattr(m,'ROOT',tmp_path);monkeypatch.setattr(m,'DAILY_DIRS',('daily',))
    (tmp_path/'daily').mkdir();(tmp_path/'daily/sh600000_daily_qfq.parquet').touch()
    rows=m.discover({'600000':'浦发银行','000001':'平安银行','300001':'创业板','510300':'ETF'})
    assert {r[0] for r in rows}=={'sh600000','sz000001'}
    assert len(next(r[2] for r in rows if r[0]=='sz000001'))==0


def test_cache_close_timestamp_uses_shanghai_calendar_date(tmp_path):
    p=tmp_path/'daily.parquet'
    pd.DataFrame({'date':pd.to_datetime(['2026-10-21 15:00','2026-10-22 15:00']).tz_localize('Asia/Shanghai')}).to_parquet(p)
    assert m.cache_dates(p).iloc[-1]==pd.Timestamp('2026-10-22')


def test_stale_data_and_no_volume_cannot_be_current_candidate():
    d=pd.DataFrame({'date':pd.bdate_range('2026-01-01',periods=150),'volume':1000.})
    day=d.date.max()
    assert m.eligibility(d,day)=='ready'
    assert m.eligibility(d,day+pd.Timedelta(days=1))=='stale'
    d.loc[d.index[-1],'volume']=0
    assert m.eligibility(d,day)=='no_volume'


def test_no_unfinished_or_weekend_day():
    assert m.completed_day('2026-10-23 10:00+08:00')==pd.Timestamp('2026-10-22')
    assert m.completed_day('2026-10-25 16:00+08:00')==pd.Timestamp('2026-10-23')


def test_binding_change_invalidates_scan():
    a={'rule':{'volume':1.5},'policy':{'stop':.04}}
    b={'rule':{'volume':1.2},'policy':{'stop':.04}}
    assert m.config_hash(a)!=m.config_hash(b)
