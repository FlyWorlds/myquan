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
    assert phase_at(at('11:30:00')) == 'day_low_rebound'
    assert phase_at(at('11:30:01')) is None
    assert phase_at(at('12:00:00')) is None
    assert phase_at(at('13:00:00')) is None
    assert phase_at(at('14:00:00')) is None

def test_no_breakout_after_ten_and_no_early_rebound():
    q=quote(last=10.3)
    assert not is_trigger(order('breakout'),q,at('10:00:01'),at('10:00:01'))
    q=quote('09:59:59')
    assert not is_trigger(order('day_low_rebound'),q,at('09:59:59'),at('09:59:59'))

def test_rebound_uses_observed_pullback_not_day_low():
    from attack_wave import AttackWaves
    from unittest.mock import patch
    waves = AttackWaves()
    o = dict(order('day_low_rebound'), code='600967', open=12.46, entry_pct=.02)
    with patch('attack_wave.WAVES', waves):
        for clock, px in [('10:00:01',12.63), ('10:01:01',12.59), ('10:02:01',12.72)]:
            q = quote(clock, open=12.46, prev_close=12.46, low=12.30, high=13.2, last=px)
            waves.observe('600967', q, at(clock))
            assert not is_trigger(o,q,at(clock),at(clock))
        assert effective_order(o,q)['price'] == 12.85
        q = quote('10:03:01',open=12.46,prev_close=12.46,low=12.30,high=13.2,last=12.85)
        waves.observe('600967',q,at('10:03:01'))
        assert is_trigger(o,q,at('10:03:01'),at('10:03:01'))
        # Even a one-tick pullback starts a new wave, without reusing 12.59.
        q = quote('10:04:01',open=12.46,prev_close=12.46,low=12.30,high=13.2,last=12.84)
        waves.observe('600967',q,at('10:04:01'))
        assert effective_order(o,q)['price'] == 13.1
        assert not is_trigger(o,q,at('10:04:01'),at('10:04:01'))
        # 13:00 后严禁新开仓，即使价格满足也绝不触发
        q_afternoon = quote('13:05:00',open=12.46,prev_close=12.46,low=12.30,high=13.5,last=13.1)
        assert not is_trigger(o, q_afternoon, at('13:05:00'), at('13:05:00'))


def test_auction_starts_at_0925_without_historical_backfill():
    o=order('auction_open');o['price']=10
    assert is_trigger(o,quote('09:25:02',low=10,last=10),at('09:25:02'),at('09:25:02'))
    assert not is_trigger(o,quote('09:24:59',low=10,last=10),at('09:24:59'),at('09:24:59'))
    assert not is_trigger(o,quote('09:25:02',low=10,last=10,_open_finalized=False),at('09:25:02'),at('09:25:02'))
    assert not is_trigger(o,quote('09:25:02',low=10,last=10),at('09:25:02'),at('09:25:08'))
    assert is_trigger(o,quote('09:30:01',low=10,last=10.1),at('09:30:01'),at('09:30:01'))
    assert not is_trigger(o,quote('09:30:06',low=10,last=10.1),at('09:30:06'),at('09:30:06'))

def test_early_each_one_late_reuses_all_unused_slots():
    trades=[dict(side='buy',session=DAY,time=DAY+' 09:30:01',signal_factor='factor29')]
    # 竞价已买 1 只
    assert quota_reason(order('auction_open'),trades,DAY) == 'ENTRY_PHASE_QUOTA'
    # 竞价买了，突破还可以买 1 只
    assert quota_reason(order('breakout'),trades,DAY) is None
    trades.append(dict(side='buy',session=DAY,time=DAY+' 09:31:00',signal_factor='factor26'))
    # 突破也买了 1 只，突破不能再买
    assert quota_reason(order('breakout'),trades,DAY) == 'ENTRY_PHASE_QUOTA'
    # 关键规则：如果竞价买了且突破买了，当天总新增满2槽，探底回升就不买！
    assert quota_reason(order('day_low_rebound'),trades,DAY) == 'ENTRY_PHASE_QUOTA'

    # 若竞价没买，探底回升可以买 1 槽
    trades_no_auction = [dict(side='buy',session=DAY,time=DAY+' 09:32:00',signal_factor='factor26')]
    assert quota_reason(order('day_low_rebound'), trades_no_auction, DAY) is None
    # 但探底回升最多买 1 槽
    trades_no_auction.append(dict(side='buy',session=DAY,time=DAY+' 10:05:00',signal_factor='factor33'))
    assert quota_reason(order('day_low_rebound'), trades_no_auction, DAY) == 'ENTRY_PHASE_QUOTA'

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
    assert len(strategy1_watchlist({})) > 0
    enabled={b.factor_id for b in get_strategy_bindings('strategy1') if b.enabled}
    assert {'factor29','factor33'} <= enabled


def test_dip_rebound_break_open():
    """测试因子33：必须低开、最低价 < 开盘价-3%、回升突破开盘价才触发买入，且以信号价格成交。"""
    from attack_wave import AttackWaves
    from unittest.mock import patch
    waves = AttackWaves()
    o = dict(order('day_low_rebound'), code='601020', open=10.00, prev_close=10.20, entry_pct=.015, tick=.01)
    with patch('attack_wave.WAVES', waves):
        # 1. 平开或高开，直接不满足低开铁律
        o_high = dict(o, open=10.25, prev_close=10.20)
        q_high = quote('10:00:01', open=10.25, prev_close=10.20, low=9.80, high=10.30, last=10.26)
        waves.observe('601020', q_high, at('10:00:01'))
        assert not effective_order(o_high, q_high)['wave_ready']

        # 2. 低开但探底不足 -3%（如最低价 9.75 > 10.00*0.97），不满足探底铁律
        q_not_deep = quote('10:00:01', open=10.00, prev_close=10.20, low=9.75, high=10.05, last=10.02)
        waves.observe('601020', q_not_deep, at('10:00:01'))
        assert not effective_order(o, q_not_deep)['wave_ready']

        # 3. 低开且最低价 9.68（探底 -3.2% < -3%），但在 9.85 时未突破开盘价 10.00，不触发
        q1 = quote('10:00:01', open=10.00, prev_close=10.20, low=9.68, high=9.95, last=9.85)
        waves.observe('601020', q1, at('10:00:01'))
        eff1 = effective_order(o, q1)
        assert eff1['price'] == 10.01
        assert not is_trigger(o, q1, at('10:00:01'), at('10:00:01'))

        # 4. 随后拉升到 10.02，突破开盘价 10.01！触发买入！
        q2 = quote('10:10:01', open=10.00, prev_close=10.20, low=9.68, high=10.10, last=10.02)
        waves.observe('601020', q2, at('10:10:01'))
        eff2 = effective_order(o, q2)
        assert eff2['price'] == 10.01
        assert is_trigger(o, q2, at('10:10:01'), at('10:10:01'))

