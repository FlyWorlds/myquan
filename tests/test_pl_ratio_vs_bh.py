"""pl_ratio_vs_bh 单元测试。"""

from __future__ import annotations

import math

from strategy.pl_ratio_vs_bh import pl_ratio_vs_bh_from_trades


def test_win_lag_and_loss_defense():
    # 盈利笔：持股 10%，策略 6% → lag=4%
    # 亏损笔：持股 -8%，策略 -3% → def=5%
    strat = [0.06, -0.03]
    bh = [0.10, -0.08]
    out = pl_ratio_vs_bh_from_trades(strat, bh)
    assert abs(out["mean_lag_pct"] - 4.0) < 1e-9
    assert abs(out["mean_def_pct"] - 5.0) < 1e-9
    assert abs(out["pl_ratio_vs_bh"] - 1.25) < 1e-9


def test_no_lag_when_strategy_beats_hold_on_win():
    strat = [0.12]
    bh = [0.10]
    out = pl_ratio_vs_bh_from_trades(strat, bh)
    assert out["mean_lag_pct"] == 0.0
    assert math.isinf(out["pl_ratio_vs_bh"])


def test_empty():
    out = pl_ratio_vs_bh_from_trades([], [])
    assert out["n_win_trades"] == 0
    assert out["pl_ratio_vs_bh"] != out["pl_ratio_vs_bh"]  # nan
