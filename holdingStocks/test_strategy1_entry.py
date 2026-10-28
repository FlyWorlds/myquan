from datetime import datetime
from strategy1_entry import phase_at, effective_order, quota_reason
from condition_buy import make_order, is_trigger
from auction_sell import draft_auction_sell, auction_sell_ready

DAY = '2026-10-28'
def at(clock): return datetime.fromisoformat(DAY+' '+clock)
def order(kind):
    return make_order(code='603138', session=DAY, open_px=10, price=10.25, entry_pct=.025,
        tick=.01, armed_at=DAY+' 09:25:01', quote_at=DAY+' 09:25:00', name='海量数据', market='SH', kind=kind)
def quote(clock='10:00:01', **extra):
    return dict(dict(session=DAY, open=10, low=9, high=10.5, last=9.23,
        last_ts=DAY+' '+clock, prev_close=10, _quote_source='sina_batch'), **extra)

def test_phase_boundaries():
    assert phase_at(at('09:24:59')) is None
    assert phase_at(at('09:25:00')) == 'auction_open'
    assert phase_at(at('09:30:00')) == 'breakout'
    assert phase_at(at('09:59:59')) == 'breakout'
    assert phase_at(at('10:00:00')) == 'day_low_rebound'
    assert phase_at(at('12:00:00')) is None
    assert phase_at(at('13:00:00')) == 'day_low_rebound'

def test_no_breakout_after_ten_and_no_early_rebound():
    q=quote(last=10.3)
    assert not is_trigger(order('breakout'),q,at('10:00:01'),at('10:00:01'))
    q=quote('09:59:59')
    assert not is_trigger(order('day_low_rebound'),q,at('09:59:59'),at('09:59:59'))

def test_rebound_threshold_follows_new_low_without_using_high_as_trigger():
    o=order('day_low_rebound');q=quote()
    assert effective_order(o,q)['price'] == 9.23
    assert is_trigger(o,q,at('10:00:01'),at('10:00:01'))
    assert not is_trigger(o,quote(last=9.22),at('10:00:01'),at('10:00:01'))
    assert effective_order(o,quote(low=8, last=8.2))['price'] == 8.2
    assert o['price'] == 10.25

def test_auction_only_bell_no_historical_backfill():
    o=order('auction_open');o['price']=10
    assert is_trigger(o,quote('09:30:01',low=10,last=10.1),at('09:30:01'),at('09:30:01'))
    assert not is_trigger(o,quote('09:30:06',low=10,last=10.1),at('09:30:06'),at('09:30:06'))

def test_early_each_one_late_reuses_all_unused_slots():
    trades=[dict(side='buy',session=DAY,time=DAY+' 09:30:01',signal_factor='factor29')]
    assert quota_reason(order('auction_open'),trades,DAY) == 'ENTRY_PHASE_QUOTA'
    assert quota_reason(order('breakout'),trades,DAY) is None
    trades.append(dict(side='buy',session=DAY,time=DAY+' 09:31:00',signal_factor='factor26'))
    assert quota_reason(order('breakout'),trades,DAY) == 'ENTRY_PHASE_QUOTA'
    for i in range(5):
        assert quota_reason(order('day_low_rebound'),trades,DAY) is None
        trades.append(dict(side='buy',session=DAY,signal_factor='factor33'))

def test_factor29_sell_t1_and_real_path_required():
    pos=dict(qty=100,buy_time='2026-10-27 10:00:00')
    q=quote('09:25:01',last=10,low=10,_auction_baseline=10,_auction_high=10,_auction_low=9.7,_auction_ts=DAY+' 09:24:59')
    draft=draft_auction_sell(pos,q,session=DAY,now=at('09:25:01'),entry_pct=.025)
    assert draft and draft['signal_factor']=='factor29'
    assert auction_sell_ready(draft,pos,quote('09:30:01'),session=DAY,now=at('09:30:01'))
    assert not draft_auction_sell(dict(pos,buy_time=DAY+' 09:20:00'),q,session=DAY,now=at('09:25:01'),entry_pct=.025)
    assert not draft_auction_sell(pos,quote('09:25:01'),session=DAY,now=at('09:25:01'),entry_pct=.025)

def test_strategy1_contains_sea_data_and_new_factors():
    from watch_config import strategy1_watchlist
    from strategy import get_strategy_bindings
    assert any(w['code']=='603138' and w['name']=='海量数据' for w in strategy1_watchlist({}))
    enabled={b.factor_id for b in get_strategy_bindings('strategy1') if b.enabled}
    assert {'factor29','factor33'} <= enabled
