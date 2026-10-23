"""信号时点、T+1、成交约束与策略隔离的回归测试。"""
import pandas as pd
from dataclasses import replace
from strategy.strategies.strategy3.reversal import Policy, build_features, load_daily
from strategy.strategies.strategy3.research import simulate


def fixture():
    dates = pd.bdate_range('2025-01-01', periods=8)
    d = pd.DataFrame(dict(date=dates, open=[10,10,10,10,10,10,10,10],
                          close=[10,10,8,8,10,10,10,10],
                          high=[11]*8, low=[7]*8, volume=[10000]*8,
                          anchor=[11]*8, anchor_date=['2024-12-01']*8,
                          depth=[.1]*8, broken=[True]*8, accelerated=[True]*8,
                          stabilize=[True]*8, state=['止跌']*8, mom3=[-.03]*8))
    return d


def test_features_never_rewrite_prefix():
    d, _ = load_daily('sz002273')
    d = d.iloc[:220]
    full = build_features(d, 'sz002273')
    short = build_features(d.iloc[:170], 'sz002273')
    pd.testing.assert_frame_equal(full.iloc[:170].reset_index(drop=True), short)


def test_entry_next_open_and_stop_next_day_and_cash():
    f = fixture()
    _, eq, orders, cycles = simulate({'sz000001': f}, Policy(stop=.06), initial_cash=100000)
    assert orders.iloc[0].date == '2025-01-02'
    assert orders.iloc[1].date == '2025-01-06'  # 1/3收盘止损，1/6开盘执行
    assert orders.iloc[1].side == 'sell'
    assert cycles.iloc[0].hold_days == 2
    assert eq.cash.min() >= 0
    assert all(orders.shares % 100 == 0)
    assert len(orders[orders.side=='buy']) == 1  # 同一个前底不重复进场


def test_limit_open_defer_exit_without_future_high_low():
    f = fixture().astype({'open': float})
    f.loc[3, 'open'] = 7.2  # 昨收8，跌停开盘，虽盘中打开仍保守不卖
    _, _, orders, _ = simulate({'sz000001': f}, Policy(stop=.06), initial_cash=100000)
    assert orders.iloc[1].date == '2025-01-07'
    # 当日极值不得改变开盘成交判断。
    g = f.copy(); g.loc[3, ['high', 'low']] = [9, 6]
    _, _, other, _ = simulate({'sz000001': g}, Policy(stop=.06), initial_cash=100000)
    pd.testing.assert_frame_equal(orders, other)


def test_direct_and_stabilize_differ():
    f = fixture(); f['stabilize'] = False
    a, *_ = simulate({'sz000001': f}, Policy(mode='stabilize'), initial_cash=100000)
    b, *_ = simulate({'sz000001': f}, Policy(mode='break'), initial_cash=100000)
    assert a['n_trades'] == 0 and a['open_positions'] == 0
    assert b['n_trades'] > 0


def test_registry_clears_old_factor1():
    from strategy import get_strategy, get_strategy_bindings
    assert get_strategy('strategy3').name == '策略三·鲍鱼捞饭'
    assert {b.factor_id for b in get_strategy_bindings('strategy3')} == {'factor30','factor31','factor32'}
    assert any(b.factor_id == 'factor1' for b in get_strategy_bindings('strategy8'))


def test_partial_take_profit_and_addition_only_once():
    f = fixture().astype({'open': float, 'close': float})
    f['open'] = 10.; f['close'] = 10.
    f.loc[2, 'close'] = 9.5  # 第二个持有日收盘，触发补仓条件
    f.loc[3, 'open'] = 9.5
    f.loc[4, 'close'] = 11.
    _, eq, orders, _ = simulate({'sz000001': f}, Policy(stop=.2,take=.06,reduce=.5), initial_cash=100000)
    assert (orders.reason == '补跌止跌').sum() == 1
    initial = orders.iloc[0].shares
    assert (orders[orders.reason=='分批止盈'].shares < initial*2).all()
    assert (orders.reason == '分批止盈').any()
    assert eq.cash.min() >= 0
