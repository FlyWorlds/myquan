import pandas as pd
from backtest.compare_strategy1_pools import complete_days, simulate
from backtest.strategy1_pool_1m import run as legacy


def test_pool16_does_not_follow_default_strategy(monkeypatch):
    monkeypatch.setattr(legacy, 'strategy16_watchlist', lambda: [{'code':'000070'}])
    monkeypatch.setattr(legacy, 'strategy_watchlist', lambda: [{'code':'600330'}])
    assert legacy._load_pool('strategy16') == [{'code':'000070'}]


def test_complete_days_rejects_interior_gap():
    times=list(pd.date_range('2026-10-27 09:31','2026-10-27 11:30',freq='min'))
    times+=list(pd.date_range('2026-10-27 13:01','2026-10-27 14:57',freq='min'))
    times+=[pd.Timestamp('2026-10-27 15:00')]
    frame=pd.DataFrame({'ts':times})
    assert complete_days(frame)=={'2026-10-27'}
    assert complete_days(frame.drop(50))==set()


def stock(code, rows):
    prior=pd.bdate_range(end='2026-10-26',periods=30)
    # Flat bars pass yesterday-shape and double-yang filters.
    daily=pd.DataFrame(dict(date=prior,open=10.,high=10.,low=10.,close=10.))
    minutes=pd.DataFrame(rows,columns=['ts','open','high','low','close'])
    minutes['ts']=pd.to_datetime(minutes.ts)
    return dict(w=dict(code=code,name=code,entry_pct=.025),daily=daily,minutes=minutes)


def test_phase_quota_rebound_and_t1_accounting():
    rows=[('2026-10-27 09:31',10,10.4,10,10.3),
          ('2026-10-27 10:00',10.3,10.3,9,9.3),
          ('2026-10-27 10:01',9.3,9.3,8,8.3),
          ('2026-10-27 15:00',8.3,8.3,8.3,8.3)]
    p=simulate([stock('600001',rows),stock('600002',rows)],['2026-10-27'])
    buys=[t for t in p['trades'] if t['side']=='buy']
    assert len(buys)==2
    assert [t['kind'] for t in buys]==['breakout','day_low_rebound']
    assert buys[1]['px']==9.3  # observed quote, not historical low × threshold
    assert not any(t['side']=='sell' for t in p['trades'])
    assert p['accounting']['accounting_verified']


def test_after_ten_open_breakout_is_replaced_by_rebound():
    rows=[('2026-10-27 09:31',10,10,10,10),
          ('2026-10-27 10:00',10,10.3,9,9.1),
          ('2026-10-27 15:00',9.1,9.1,9.1,9.1)]
    p=simulate([stock('600001',rows)],['2026-10-27'])
    assert p['summary']['n_buys']==0


def test_half_exit_advances_stage_and_reconciles_remaining_shares(monkeypatch):
    import backtest.compare_strategy1_pools as replay
    stages=[]
    def quote_exit(pos,quote,**kwargs):
        if quote['session']=='2026-10-28':
            stages.append(pos.get('tp_stage',0))
            if pos.get('tp_stage',0)==0:
                return dict(updates={},watermark={},action=dict(kind='half',reason='ladder_half_10',shares=100))
        return None
    monkeypatch.setattr(replay,'evaluate_quote_exit',quote_exit)
    rows=[('2026-10-27 09:31',10,10.3,10,10.3),
          ('2026-10-27 15:00',10.3,10.3,10.3,10.3),
          ('2026-10-28 09:31',10.3,10.3,10.3,10.3),
          ('2026-10-28 09:32',10.3,10.3,10.3,10.3),
          ('2026-10-28 15:00',10.3,10.3,10.3,10.3)]
    p=simulate([stock('600001',rows)],['2026-10-27','2026-10-28'])
    assert stages[:2]==[0,1]
    assert p['summary']['n_sells']==1
    assert p['accounting']['accounting_verified']


def test_rebuy_uses_actual_stop_sale_not_intraday_low(monkeypatch):
    import backtest.compare_strategy1_pools as replay
    def exit_once(pos, quote, **kwargs):
        if quote['last_ts']=='2026-10-28 10:00:00':
            return dict(updates={},watermark={},action=dict(kind='full',reason='hard_from_cost',shares=pos['qty']))
        return None
    monkeypatch.setattr(replay,'evaluate_quote_exit',exit_once)
    rows=[('2026-10-27 09:31',10,10.3,10,10.3),
          ('2026-10-27 15:00',10.3,10.3,10.3,10.3),
          ('2026-10-28 09:31',10.3,10.3,10.3,10.3),
          ('2026-10-28 10:00',10.3,10.3,9,10),
          ('2026-10-28 10:01',10,10.1,9,10.1),
          ('2026-10-28 10:02',10.1,10.16,9,10.16),
          ('2026-10-28 15:00',10.16,10.16,10.16,10.16)]
    p=simulate([stock('600001',rows)],['2026-10-27','2026-10-28'])
    rebuys=[t for t in p['trades'] if t.get('is_rebuy')]
    assert len(rebuys)==1
    assert rebuys[0]['ts']=='2026-10-28 10:02:00'
    assert rebuys[0]['rebuy_reference_px']==10
    assert rebuys[0]['trigger_price']==10.15
    assert rebuys[0]['px']==10.16
    assert p['accounting']['accounting_verified']


def test_new_morning_stop_can_change_fills_without_changing_other_rules():
    rows=[('2026-10-27 09:31',10,10.3,10,10.3),
          ('2026-10-27 15:00',10.3,10.3,10.3,10.3),
          ('2026-10-28 09:31',10.3,10.3,10.19,10.19),
          ('2026-10-28 15:00',10.19,10.3,10.19,10.3)]
    s=[stock('600001',rows)]; days=['2026-10-27','2026-10-28']
    a=simulate(s,days,current_attack_wave=True)
    b=simulate(s,days,current_attack_wave=True,morning_open_stop=True,morning_stop_start='2026-10-28')
    assert a['equity'][0]==b['equity'][0]
    assert a['summary']['n_sells']==0 and b['summary']['n_sells']==1
    assert b['trades'][-1]['exit_reason']=='s1_morning_open_stop'
    assert b['trades'][-1]['px']==10.19
    assert a['summary']['final_equity']>b['summary']['final_equity']


def test_current_wave_waits_for_observed_fall_then_rebound():
    rows=[('2026-10-27 09:31',10,10,10,10),
          ('2026-10-27 10:00',10,10.3,9,10.3),
          ('2026-10-27 10:01',10.3,10.3,10,10),
          ('2026-10-27 10:02',10,10.3,10,10.3),
          ('2026-10-27 15:00',10.3,10.3,10.3,10.3)]
    r=simulate([stock('600001',rows)],['2026-10-27'],current_attack_wave=True)
    assert len(r['trades'])==1
    assert r['trades'][0]['ts']=='2026-10-27 10:02:00'
    assert r['trades'][0]['trigger_price']==10.25
