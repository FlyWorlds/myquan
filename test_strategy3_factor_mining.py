import pandas as pd
from strategy.strategies.strategy3.reversal import load_daily
from strategy.strategies.strategy3.factor_mining import features, FactorRule, signal, event_observations, stats


def test_structure_features_are_causal():
    d,_=load_daily('sz002273')
    full=features(d.iloc[:450],'sz002273')
    prefix=features(d.iloc[:350],'sz002273')
    pd.testing.assert_frame_equal(full.iloc[:350].reset_index(drop=True),prefix)
    b=full[full.broken]
    assert len(b)>0
    assert (pd.to_datetime(b.anchor_date)<pd.to_datetime(b.top_date)).all()
    assert (pd.to_datetime(b.top_date)<=pd.to_datetime(b.known_date)).all()
    assert (pd.to_datetime(b.known_date)<b.date).all()
    assert b.down_leg.all()
    assert (b.low<b.anchor).any()
    assert not any(c.startswith('return_') for c in full.columns)


def test_factor_combinations_and_window():
    f=pd.DataFrame(dict(broken=[True]*3,break_age=[0,3,11],depth=[.01,.03,.05],
        break_volume=[1.,2.,2.],accelerated=[False,True,True],small_bear=[True]*3,
        shadow=[False]*3,higher_low=[True]*3,bullish=[True]*3,bottom3=[False]*3,
        recovered=[False]*3,stage20=[True]*3,stage60=[False]*3,dry=[True]*3,room_ratio=[2.]*3))
    assert signal(f,FactorRule(trigger='small_bear',volume=1.5,acceleration=True)).tolist()==[False,True,False]
    assert not signal(f,FactorRule(support='stage60',trigger='small_bear')).any()


def test_volume_denominator_excludes_current_day():
    d,_=load_daily('sz002273');d=d.iloc[:100].copy()
    a=features(d,'sz002273')
    d.loc[99,'volume']*=3
    b=features(d,'sz002273')
    assert abs(b.vol_ratio.iloc[-1]/a.vol_ratio.iloc[-1]-3)<1e-10
    pd.testing.assert_frame_equal(a.iloc[:-1],b.iloc[:-1])


def test_label_maturity_does_not_cross_validation_boundary():
    obs=pd.DataFrame(dict(entry_date=['2024-12-20','2024-12-30'],label_end_10=['2024-12-31','2025-01-15'],
                          return_10=[.02,.5],mae_10=[-.02,-.1]))
    s=stats(obs,'2024-01-01','2024-12-31')
    assert s['n']==1 and abs(s['mean_pct']-2)<1e-9


def test_structural_stop_and_risk_sizing_use_only_entry_information():
    from strategy.strategies.strategy3.reversal import Policy
    from strategy.strategies.strategy3.research import simulate
    from test_strategy3_abalone import fixture
    f=fixture().astype({'open':float,'close':float})
    f['open']=10.;f['close']=10.
    f['atr']=.2;f['trough']=9.5;f['anchor']=11.
    p=Policy(initial=1.,stop_mode='event_low',take_mode='anchor',risk_budget=.005,min_rr=1.5,max_entry_risk=.08)
    _,_,orders,_=simulate({'sz000001':f},p,initial_cash=100000)
    # 每票预算2万，风险预算仅500元；到9.44失效位的风险约5.7%，股数应受风险预算限制。
    assert orders.iloc[0].shares*orders.iloc[0].price<=10000
    f['anchor']=10.1
    _,_,orders,_=simulate({'sz000001':f},p,initial_cash=100000)
    assert orders.empty  # 离反弹目标过近，盈亏空间不足，不买。


def test_cache_merge_can_fill_internal_gap(tmp_path,monkeypatch):
    from strategy.strategies.strategy3 import reversal
    dates=pd.bdate_range('2025-01-01',periods=80)
    d=pd.DataFrame(dict(date=dates,open=10.,high=11.,low=9.,close=10.,volume=100.,symbol='sz000001'))
    newer=d.drop(index=35)
    older=d.iloc[20:60]
    for folder,frame in [('data_cache',newer),('data_cache/ai_concept',older)]:
        path=tmp_path/folder;path.mkdir(parents=True,exist_ok=True)
        frame.to_parquet(path/'sz000001_daily_qfq.parquet',index=False)
    monkeypatch.setattr(reversal,'ROOT',tmp_path)
    merged,_=reversal.load_daily('sz000001')
    assert len(merged)==80 and dates[35] in merged.date.values
