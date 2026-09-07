"""策略十五 · 连板减磨损 状态机单测。"""

from __future__ import annotations

from strategy.core.context import MarketContext
from strategy.ladder_tp import resolve_ladder_tp_policy
from strategy.strategies.strategy15.decision import create_decision_engine


def test_chop_enables_f22_and_tight_tp():
    p = resolve_ladder_tp_policy(max_height=2, ladder_score=3, lianban=1)
    assert p.use_factor22 is True
    assert p.regime == "chop"
    assert p.tp_pct <= 0.08


def test_hot_disables_f22():
    p = resolve_ladder_tp_policy(max_height=7, ladder_score=30, lianban=12)
    assert p.use_factor22 is False
    assert p.regime == "hot"
    assert p.tp_pct >= 0.12


def test_std_height_ten_pct():
    p = resolve_ladder_tp_policy(max_height=3, ladder_score=12, lianban=4)
    assert abs(p.tp_pct - 0.10) < 1e-9
    assert p.use_factor22 is True


def test_decision_take_profit_half():
    eng = create_decision_engine()
    ctx = MarketContext(
        open=10.0,
        high=11.2,
        low=9.9,
        close=11.1,
        session="20260818",
        position_qty=1000,
        available_qty=1000,
        entry_price=10.0,
        meta={"mkt_max_height": 3, "mkt_ladder_score": 12, "mkt_lianban": 4},
    )
    d = eng.decide(ctx)
    assert d.action == "sell"
    assert d.factor_id == "factor23"
    assert d.size_mode == "qty"


def test_decision_skips_f22_when_hot():
    eng = create_decision_engine()
    ctx = MarketContext(
        open=10.0,
        high=10.5,
        low=9.5,
        close=10.4,
        last=10.4,
        session="20260818",
        position_qty=0,
        meta={
            "stop_sold_today": True,
            "mkt_max_height": 8,
            "mkt_ladder_score": 40,
            "mkt_lianban": 15,
        },
    )
    d = eng.decide(ctx)
    assert d.action != "buy" or d.factor_id != "factor22"
