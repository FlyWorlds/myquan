import pandas as pd
from pathlib import Path
from strategy.strategies.strategy3.round2_features import enrich_features,entry_mask
from strategy.strategies.strategy3.reversal import ROOT


def fixture():
    n=8
    f=pd.DataFrame(dict(date=pd.bdate_range('2026-01-01',periods=n),open=[9.7]*n,high=[10.]*n,
        low=[9.2]*n,close=[9.8]*n,volume=[1000.]*n,event_id=['e']*n,anchor=[10.]*n,peak=[12.]*n,
        trough=[9.2]*n,break_age=list(range(n)),broken=[True]*n,break_volume=[2.]*n,vol_ratio=[1.]*n,
        anchor_date=['2025-11-01']*n,top_date=['2025-12-01']*n,known_date=['2025-12-02']*n,
        accelerated=[False]*n,stage20=[False]*n,stage60=[False]*n,stage120=[False]*n,down_leg=[True]*n,
        depth=[.08]*n,atr=[.4]*n,shadow=[False]*n,recovered=[False]*n))
    return f


def test_prefix_causality_both_structure_modes():
    raw=pd.read_parquet(ROOT/'backtest/strategy3_abalone/ytd_2026/sz002273_features.parquet').iloc[:450]
    for allow in (False,True):
        a=enrich_features(raw,allow_rebound=allow)
        b=enrich_features(raw.iloc[:350],allow_rebound=allow)
        pd.testing.assert_frame_equal(a.iloc[:350].reset_index(drop=True),b)


def test_shadow_confirmation_must_be_after_broken_shadow():
    f=fixture();f.loc[0,'shadow']=True
    f.loc[1,['high','low','close']]=[10.3,9.4,10.1]
    g=enrich_features(f)
    assert not g.shadow_confirm.iloc[0] and g.shadow_confirm.iloc[1]
    f.loc[0,'broken']=False;f.loc[0,'break_age']=-1
    assert not enrich_features(f).shadow_confirm.iloc[1]


def test_reclaim_needs_two_post_break_closes():
    f=fixture();f['close']=10.1
    f.loc[0,'broken']=False;f.loc[0,'break_age']=-1
    g=enrich_features(f)
    assert not g.reclaim2.iloc[1]
    assert g.reclaim2.iloc[2]


def test_completed_target_setup_cannot_rearm_same_event():
    f=fixture();f.loc[2,'close']=12.1
    g=enrich_features(f,allow_rebound=True)
    assert g.setup_valid.iloc[1]
    assert not g.setup_valid.iloc[2:].any()


def test_new_up_leg_can_confirm_only_in_explicit_rebound_mode():
    f=fixture();f.loc[2:,'down_leg']=False;f.loc[2:,'broken']=False
    f.loc[0,'shadow']=True;f.loc[2,['high','low','close']]=[10.4,9.3,10.2]
    r=dict(window=10,volume=1.5,trigger='shadow_confirm',quality_filter='none')
    assert not entry_mask(enrich_features(f),{**r,'allow_rebound':False}).iloc[2]
    assert entry_mask(enrich_features(f,allow_rebound=True),{**r,'allow_rebound':True}).iloc[2]
