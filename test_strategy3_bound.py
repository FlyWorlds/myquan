import pandas as pd
from strategy.abalone_risk import entry_plan
from strategy.strategies.strategy3.reversal import Policy
from strategy.strategies.strategy3.research import simulate
from test_strategy3_abalone import fixture


def bars():
    d=fixture().astype({'open':float,'close':float,'low':float})
    d['open']=10.;d['close']=10.;d['low']=9.8;d['high']=11.
    d['trough']=9.5;d['atr']=.2;d['peak']=12.;d['anchor']=11.
    return d


def policy(**kwargs):
    return Policy(initial=1.,stop_mode='event_low',stop_buffer_atr=0.,take_mode='structure',**kwargs)


def test_targets_change_after_reclaim_and_c_never_moves():
    r=bars().iloc[0]
    p=policy().dict()
    a=entry_plan(r,10.,p);b=entry_plan(r,11.2,p)
    assert a['target_px']==11 and a['second_target_px']==12
    assert b['target_px']==12 and b['second_target_px'] is None
    assert a['stop_px']==b['stop_px']==9.5
    assert not entry_plan(r,12.1,p)['allowed']


def test_over_night_gap_stop_uses_open_not_stop_line():
    d=bars();d.loc[2,['open','low','close']]=[9.2,9.1,9.4]
    _,_,orders,_=simulate({'sz000001':d},policy(stop_trigger='intraday'),initial_cash=100000)
    sell=orders[orders.side=='sell'].iloc[0]
    assert sell.price==9.2*.999 and sell.stop_px==9.5


def test_intraday_and_close_confirmation_differ():
    d=bars();d.loc[2,'low']=9.4
    _,_,intraday,_=simulate({'sz000001':d},policy(stop_trigger='intraday'),initial_cash=100000)
    _,_,close,_=simulate({'sz000001':d},policy(stop_trigger='close'),initial_cash=100000)
    assert len(intraday[intraday.side=='sell'])==1
    assert not len(close[close.side=='sell'])
    assert intraday[intraday.side=='sell'].iloc[0].price==9.5*.999


def test_buy_day_touch_cannot_be_sold_same_day():
    d=bars();d.loc[1,'low']=9.4
    _,_,orders,_=simulate({'sz000001':d},policy(stop_trigger='intraday'),initial_cash=100000)
    assert orders.iloc[0].date=='2025-01-02'
    assert orders.iloc[1].date=='2025-01-03'
    assert orders.iloc[1].reason=='T+1次开止损'


def test_c_frozen_and_not_lowered_after_new_low():
    d=bars();d.loc[2,['low','close']]=[9.3,9.4];d.loc[2:,'trough']=8.
    _,_,orders,_=simulate({'sz000001':d},policy(stop_trigger='close'),initial_cash=100000)
    sell=orders[orders.side=='sell'].iloc[0]
    assert sell.stop_px==9.5


def test_partial_take_then_same_day_stop_remainder():
    d=bars();d.loc[2,'close']=11.2;d.loc[2,'high']=11.3
    d.loc[3,['open','high','low','close']]=[11.2,11.3,9.4,9.8]
    _,_,orders,cycles=simulate({'sz000001':d},policy(stop_trigger='intraday'),initial_cash=100000)
    sales=orders[orders.side=='sell']
    assert len(sales)==2 and sales.date.nunique()==1
    assert sales.iloc[0].reason=='分批止盈'
    assert sales.iloc[1].reason=='减仓后同日触价止损'
    assert len(cycles)==1


def test_factor_binding_real_functions_and_decision_guard():
    from strategy import get_strategy_bindings,get_decision_engine
    from strategy.core.context import MarketContext
    bs=get_strategy_bindings('strategy3')
    assert {x.factor_id for x in bs}=={'factor30','factor31','factor32'}
    eng=get_decision_engine('strategy3')
    ctx=MarketContext(open=10,high=20,low=1,close=10,session='2025-01-03')
    assert eng.decide(ctx).action=='hold'
    row=dict(date='2025-01-03',broken=True,down_leg=True,break_age=1,event_id='x',
             shadow=True,recovered=True,break_volume=5.,anchor=11.,peak=12.,trough=9.5,atr=.2,close=10,low=9.8)
    ctx.meta=dict(strategy3_daily_feature=row,strategy3_next_open=True)
    assert eng.decide(ctx).action=='hold' # 未完成当日K线禁止回填
    row['date']='2025-01-02'
    assert eng.decide(ctx).action=='buy'


def test_later_low_after_open_full_exit_not_used_for_new_low_diagnostic():
    d=bars();d.loc[2,['close','high']]=[11.2,11.3]
    d.loc[3,['open','high','low','close']]=[11.3,11.4,8.,9.]
    _,_,_,cycles=simulate({'sz000001':d},policy(reduce=1.,stop_trigger='close'),initial_cash=100000)
    assert not bool(cycles.iloc[0].new_low_after_entry)


def test_mutating_binding_changes_real_entry_decision():
    from dataclasses import replace
    from strategy import get_strategy_bindings
    from strategy.core.context import MarketContext
    from strategy.strategies.strategy3.decision import Strategy3Decision
    bs=tuple(get_strategy_bindings('strategy3'))
    altered=tuple(replace(b,params={**b.params,'volume':999.}) if b.factor_id=='factor31' else b for b in bs)
    row=dict(date='2025-01-02',broken=True,down_leg=True,break_age=1,event_id='x',shadow=True,recovered=True,
             break_volume=5.,anchor=11.,peak=12.,trough=9.5,atr=.2,close=10,low=9.8)
    ctx=MarketContext(open=10,high=50,low=1,close=10,session='2025-01-03',
                      meta=dict(strategy3_daily_feature=row,strategy3_next_open=True))
    assert Strategy3Decision(bs).decide(ctx).action=='buy'
    assert Strategy3Decision(altered).decide(ctx).action=='hold'
