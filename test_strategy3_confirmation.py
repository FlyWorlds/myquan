import pandas as pd
from strategy.strategies.strategy3.confirmation_study import confirm_frame
from test_strategy3_round2 import fixture


def signal_frame():
    f=fixture();f['stabilize']=False;f.loc[0,'stabilize']=True
    f.loc[1,['open','close','low']]=[9.4,9.6,9.1]
    return f


def test_next_day_green_only_and_no_same_day_entry_signal():
    f=signal_frame();g=confirm_frame(f,'bullish',list(f.date))
    assert not g.stabilize.iloc[0] and g.stabilize.iloc[1]
    assert not g.stabilize.iloc[2:].any()
    assert g.open.iloc[1]==f.open.iloc[1] and g.date.iloc[1]==f.date.iloc[1]
    assert g.trough.iloc[1]==9.1


def test_stricter_confirmation_rejects_lower_low_and_doji():
    f=signal_frame()
    assert not confirm_frame(f,'bullish_no_new_low',list(f.date)).stabilize.any()
    f.loc[1,'low']=9.3
    assert confirm_frame(f,'bullish_no_new_low',list(f.date)).stabilize.iloc[1]
    f.loc[1,'close']=f.open.iloc[1]
    assert not confirm_frame(f,'bullish',list(f.date)).stabilize.any()


def test_no_future_leak_and_original_structure_survives_native_switch():
    f=signal_frame();f.loc[1,['event_id','anchor','peak']]=['new-event',8.,11.]
    a=confirm_frame(f,'bullish',list(f.date));b=confirm_frame(f.iloc[:2],'bullish',list(f.date))
    pd.testing.assert_frame_equal(a.iloc[:2],b)
    assert a.event_id.iloc[1]=='e' and a.anchor.iloc[1]==10. and a.peak.iloc[1]==12.


def test_missing_next_market_day_is_not_late_confirmation():
    f=signal_frame();calendar=list(f.date);g=f.drop(index=1).reset_index(drop=True)
    assert not confirm_frame(g,'bullish',calendar).stabilize.any()


def test_confirmed_signal_executes_only_following_open():
    from strategy.strategies.strategy3.research import simulate
    from strategy.strategies.strategy3.reversal import Policy
    f=signal_frame();f['anchor_date']=f.event_id
    g=confirm_frame(f,'bullish',list(f.date))
    p=Policy(depth=0,acceleration=False,initial=1,risk_budget=.005,stop=.04,take_mode='structure',hold=20)
    _,_,orders,_=simulate({'sh600000':g},p,start=str(f.date.min().date()),end=str(f.date.max().date()))
    buy=orders[orders.side=='buy'].iloc[0]
    assert buy.date==str(f.date.iloc[2].date())
