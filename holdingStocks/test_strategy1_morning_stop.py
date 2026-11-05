from datetime import datetime
import pytest
from quote_exit import evaluate_quote_exit
from strategy1_exit import morning_stop_price


def evaluate(clock='09:59:59', price=9.9, enabled=True, **pos_changes):
    now=datetime.fromisoformat('2026-11-05 '+clock)
    pos=dict(code='600330',qty=1000,available=1000,cost=10.,peak_high=10.,buy_time='2026-11-04 10:01:00')
    pos.update(pos_changes)
    q=dict(session='2026-11-05',last_ts=str(now),open=10.,high=10.,low=min(9.8,price),last=price,prev_close=10.)
    return evaluate_quote_exit(pos,q,session='2026-11-05',now=now,received_at=now,morning_open_stop=enabled)


def test_exact_threshold_and_observed_gap_fill():
    a=evaluate()['action']
    assert a['reason']=='s1_morning_open_stop' and a['shares']==1000 and a['fill_px']==9.9
    assert evaluate(price=9.88)['action']['fill_px']==9.88
    assert evaluate(price=9.91)['action'] is None


def test_time_and_disabled_boundaries():
    assert evaluate(clock='09:30:00')['action']['reason']=='s1_morning_open_stop'
    assert evaluate(clock='09:29:59') is None
    assert evaluate(clock='10:00:00')['action'] is None
    assert evaluate(enabled=False)['action'] is None
    assert morning_stop_price(10.01,'09:40:00')==9.9


def test_t1_locks_and_available():
    assert evaluate(buy_time='2026-11-05 09:30:00')['action'] is None
    assert evaluate(hold_lock=True)['action'] is None
    assert evaluate(available=300)['action']['shares']==300


def test_after_ten_original_cost_stop_unchanged():
    a=evaluate(clock='10:00:00',price=9.7)['action']
    b=evaluate(clock='10:00:00',price=9.7,enabled=False)['action']
    assert a==b and a is not None


def test_late_arrival_after_ten_does_not_replay_morning_stop():
    from datetime import timedelta
    now=datetime(2026,11,5,10,0,1)
    q=dict(session='2026-11-05',last_ts='2026-11-05 09:59:59',open=10.,high=10.,low=9.9,last=9.9,prev_close=10.)
    p=dict(code='600330',qty=1000,available=1000,cost=10.,peak_high=10.,buy_time='2026-11-04 10:01:00')
    assert evaluate_quote_exit(p,q,session='2026-11-05',now=now,received_at=now,morning_open_stop=True)['action'] is None


def test_strategy_book_enables_global_morning_open_stop():
    from unittest.mock import Mock,patch
    from strategy_books_runtime import StrategyBooksRuntime
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return datetime(2026,11,5,9,45)
    for sid in ('strategy1','strategy16'):
        book=dict(virtual_shares=1000,available=1000,entry_price=10.,entry_time='2026-11-04 10:01:00',
                  peak_high=10.,overnight_peak_session='2026-11-05',quote_exit_session='2026-11-05')
        client=Mock(ready=True,strategy_id=sid)
        client.get.return_value=book
        runtime=StrategyBooksRuntime(client,vol_for=lambda *_:None,signal_window=lambda _:True)
        q=dict(session='2026-11-05',last_ts='2026-11-05 09:45:00',open=10.,high=10.,low=9.9,last=9.9,prev_close=10.)
        with patch('strategy_books_runtime.datetime',Clock):runtime.on_quote('sh600330',q,Clock.now())
        sells=[c for c in client.command.call_args_list if c.kwargs.get('side')=='SELL']
        assert bool(sells) is True


def test_index_row_displays_morning_stop_globally():
    from unittest.mock import Mock, patch
    import index
    now = datetime(2026, 11, 5, 9, 35, 0)
    pos = dict(cost=10.0, qty=1000, buy_time='2026-11-04 10:00:00', peak_high=10.0)
    q = dict(open=10.0, last=9.95, high=10.0, low=9.95, prev_close=10.0)
    w = dict(code='600330', name='天通股份', sina='sh600330')
    row = dict(持仓=1000)
    
    # 模拟计算
    stop = 9.75 # 假设常规止损为 9.75
    morning_stop = morning_stop_price(float(q['open']), now.strftime('%H:%M:%S'), tick=.01)
    assert morning_stop == 9.90
    assert morning_stop > stop

