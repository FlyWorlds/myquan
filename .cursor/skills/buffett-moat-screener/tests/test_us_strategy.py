from __future__ import annotations

import pandas as pd
import pytest

from scripts import us_strategy


def _financial_rows() -> pd.DataFrame:
    rows = []
    for year in (2013, 2014, 2015):
        rows.append(
            {
                "symbol": "AAPL",
                "date": pd.Timestamp(f"{year}-10-28"),
                "fy_period": f"FY{year}Q4",
                "is_net_income": 20.0,
                "bs_common_equity_total": 100.0,
                "bs_total_assets": 200.0,
                "is_gross_profit": 50.0,
                "is_revenue_goods_services": 100.0,
                "cfs_capex_total": 5.0,
                "bs_debt_lt_total": 20.0,
                "is_eps_basic_inc_exord": 2.0,
                "is_op_profit_before_non_recurring": 25.0,
            }
        )
    return pd.DataFrame(rows)


def test_us_metrics_respect_publication_date_and_disclose_partial_history():
    metrics = us_strategy.build_metrics(
        _financial_rows(), "AAPL", pd.Timestamp("2015-01-02"), 20.0
    )
    assert metrics["annual_report_count"] == 2
    assert metrics["latest_fy_period"] == "FY2014Q4"
    assert metrics["roe_mean_pct"] == pytest.approx(20.0)
    assert metrics["current_pe"] == pytest.approx(10.0)
    assert 0.0 < metrics["history_coverage_ratio"] < 1.0


def test_us_split_jump_is_corrected_but_ordinary_loss_is_not():
    split_return, factor = us_strategy._split_adjusted_return(129.04, 499.23, 4.0)
    assert factor == 4.0
    assert split_return == pytest.approx(0.034, abs=0.005)
    ordinary_return, factor = us_strategy._split_adjusted_return(85.0, 100.0)
    assert factor == 1.0
    assert ordinary_return == pytest.approx(-0.15)
    crash_return, factor = us_strategy._split_adjusted_return(45.0, 100.0)
    assert factor == 1.0
    assert crash_return == pytest.approx(-0.55)


def test_annual_signal_dates_use_first_available_trading_day():
    index = pd.DatetimeIndex(["2015-01-02", "2015-01-05", "2016-01-04", "2016-01-05"])
    assert us_strategy._annual_signal_dates(index, "20150101", "20161231") == [
        pd.Timestamp("2015-01-02"),
        pd.Timestamp("2016-01-04"),
    ]


def test_us_selection_keeps_healthy_incumbents_and_caps_industries():
    candidates = [
        {"symbol": "V", "industry": "Payments", "soft_eligible": True, "sell_triggers": [], "total_score": 90},
        {"symbol": "MA", "industry": "Payments", "soft_eligible": True, "sell_triggers": [], "total_score": 89},
        {"symbol": "P3", "industry": "Payments", "soft_eligible": True, "sell_triggers": [], "total_score": 88},
    ]
    candidates += [
        {"symbol": f"X{i}", "industry": f"I{i}", "soft_eligible": True, "sell_triggers": [], "total_score": 80 - i}
        for i in range(7)
    ]
    picks = us_strategy._select_portfolio(candidates, ["MA"])
    assert picks[0] == "MA"
    assert len(set(picks) & {"V", "MA", "P3"}) == 2
    assert len(picks) == us_strategy.HOLD_TOP
