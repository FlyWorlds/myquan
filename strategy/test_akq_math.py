"""akquant 向量原语：收益率 / 今日盈亏 / 波动。"""

from __future__ import annotations

import math

import numpy as np
from akquant import vec_log_returns, vec_returns, vec_rolling_std

from strategy.akq_math import (
    log_return_sample_std,
    mark_unrealized,
    price_chg_pct,
    session_day_pnl,
    simple_return,
)


def test_simple_return_matches_vec_returns():
    prev, last = 48.59, 46.97
    got = simple_return(last, prev)
    want = float(vec_returns(np.asarray([prev, last], dtype=np.float64))[1])
    assert got == want
    pct = price_chg_pct(last, prev)
    assert pct == want * 100.0


def test_session_day_pnl_overnight_is_vec_returns():
    last, prev, qty = 46.97, 48.59, 1800
    pnl, pct, base = session_day_pnl(
        mark=last,
        qty=qty,
        cost=47.67,
        prev_close=prev,
        bought_today=False,
    )
    r = float(vec_returns(np.asarray([prev, last], dtype=np.float64))[1])
    assert pnl == round(r * prev * qty, 2)
    assert pct == round(r * 100.0, 2)
    assert base == round(prev * qty, 2)


def test_session_day_pnl_today_buy_vs_cost_not_prev_close():
    last, cost, prev, qty = 17.0, 16.29, 16.18, 5500
    pnl, pct, base = session_day_pnl(
        mark=last,
        qty=qty,
        cost=cost,
        prev_close=prev,
        bought_today=True,
    )
    assert pnl == round((last - cost) * qty, 2)
    assert base == round(cost * qty, 2)
    assert pct == round(simple_return(last, cost) * 100.0, 2)


def test_mark_unrealized_matches_entry_mark():
    pnl, pct = mark_unrealized(17.0, 16.29, 5500)
    assert pnl == round((17.0 - 16.29) * 5500, 2)
    assert pct == round(simple_return(17.0, 16.29) * 100.0, 2)


def test_log_return_sample_std_matches_akquant():
    closes = [10.0 + i * 0.2 + ((-1) ** i) * 0.15 for i in range(25)]
    got = log_return_sample_std(closes, window=20)
    arr = np.asarray(closes[-(20 + 1) :], dtype=np.float64)
    rets = vec_log_returns(arr)
    finite = rets[np.isfinite(rets)]
    want = float(vec_rolling_std(np.asarray(finite, dtype=np.float64), 20)[-1])
    assert got is not None
    assert math.isclose(got, want, rel_tol=0, abs_tol=1e-12)
