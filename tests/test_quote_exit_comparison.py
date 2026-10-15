from types import SimpleNamespace

import pandas as pd

from backtest.strategy16_core_leader.compare_quote_exit import simulate


def fixture():
    entry = SimpleNamespace(code="000070", name="Test", px=10., shares=900, ts="2026-10-14 09:31:00")
    bars = pd.DataFrame([dict(ts=pd.Timestamp("2026-10-15 09:31:00"), open=10., high=11.6, low=10., close=10.1)])
    daily = pd.DataFrame([dict(date=pd.Timestamp("2026-10-14"), close=10.)])
    return entry, bars, daily


def test_ohlc_vs_close_is_a_proxy_difference_not_tick_proof():
    entry, bars, daily = fixture()
    old = simulate(entry, bars, daily, mode="minute_ohlc", end="2026-10-15")
    proxy = simulate(entry, bars, daily, mode="minute_close_proxy", end="2026-10-15")
    assert old["remaining"] == 0
    assert proxy["remaining"] == 900
    assert old["gross_pnl"] == 1350.
    assert proxy["gross_pnl"] == 90.


def test_same_buy_day_neither_arm_sells():
    entry, bars, daily = fixture()
    entry.ts = "2026-10-15 09:30:00"
    for mode in ("minute_ohlc", "minute_close_proxy"):
        result = simulate(entry, bars, daily, mode=mode, end="2026-10-15")
        assert result["remaining"] == 900
        assert result["legs"] == 0


def test_buy_high_touch_and_close_proxy_have_explicitly_different_times():
    from backtest.strategy16_core_leader.replay_condition_day import first_touch
    bars = pd.DataFrame([
        dict(ts=pd.Timestamp("2026-10-15 09:31:00"), open=10., high=10.3, low=10., close=10.2),
        dict(ts=pd.Timestamp("2026-10-15 09:32:00"), open=10.2, high=10.35, low=10.1, close=10.3)])
    args = dict(price=10.25, official_open=10., prev_close=10., limit_pct=.10, tick=.01)
    assert first_touch(bars, **args) == "2026-10-15 09:31:00"
    assert first_touch(bars, **args, close_proxy=True) == "2026-10-15 09:32:00"
