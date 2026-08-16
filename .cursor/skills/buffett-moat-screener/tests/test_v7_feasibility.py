from __future__ import annotations

import pandas as pd
import pytest

from scripts import feasibility, reporting


def test_run_feasibility_returns_periods_costs_audit_and_holdings(monkeypatch, tmp_path):
    calendar_rows = []
    price_rows = []
    fund_rows = []
    index_rows = []
    level = 10.0
    benchmark = 10.0
    for year in range(2017, 2024):
        signal = f"{year}0430"
        execution = f"{year}0502"
        calendar_rows.extend(
            [{"date": signal, "is_open": 1}, {"date": execution, "is_open": 1}]
        )
        level *= 1.10
        benchmark *= 1.04
        price_rows.append(
            {
                "date": execution,
                "symbol": "600519.SH",
                "open": level / 1.05,
                "close": level,
                "tradable": True,
                "limit_up": False,
                "limit_down": False,
            }
        )
        fund_rows.append({"date": execution, "symbol": "510300.SH", "open": benchmark, "close": benchmark})
        index_rows.append({"date": execution, "symbol": "000300.SH", "open": benchmark, "close": benchmark})

    monkeypatch.setattr(
        feasibility.data_pipeline,
        "fetch_trade_calendar",
        lambda *args: pd.DataFrame(calendar_rows),
    )
    monkeypatch.setattr(
        feasibility.data_pipeline,
        "discover_symbols",
        lambda *args: ["600519.SH"],
    )
    monkeypatch.setattr(
        feasibility.data_pipeline,
        "fetch_financial_history",
        lambda *args, **kwargs: pd.DataFrame({"symbol": ["600519.SH"]}),
    )
    monkeypatch.setattr(
        feasibility.data_pipeline,
        "fetch_historical_industries",
        lambda *args: pd.DataFrame(),
    )
    monkeypatch.setattr(
        feasibility,
        "screen_symbols",
        lambda symbols, signal_date, **kwargs: (
            [
                    {
                        "target_id": "600519.SH",
                        "decision": "research_candidate",
                        "quality_score": 90.0,
                        "cash_earnings_yield_proxy": 0.05,
                        "normalized_pe": 20.0,
                        "entry_eligible": True,
                        "hold_status": "healthy",
                        "sell_triggers": [],
                        "industry": "食品饮料",
                        "special_case": None,
                    "metrics": {
                        "pe_lyr": 15.0,
                        "roe_ten_year_floor_pct": 18.0,
                        "capex_to_profit_5y": 0.1,
                        "gross_margin_std_pct_points": 2.0,
                    },
                    "actual_source_date": f"{int(signal_date[:4])}0331",
                }
            ],
            pd.DataFrame(),
        ),
    )
    monkeypatch.setattr(
        feasibility.data_pipeline,
        "fetch_stock_backtest_prices",
        lambda *args, **kwargs: pd.DataFrame(price_rows),
    )
    monkeypatch.setattr(
        feasibility.data_pipeline,
        "fetch_fund_post",
        lambda symbol, *args: pd.DataFrame(fund_rows),
    )
    monkeypatch.setattr(
        feasibility.data_pipeline,
        "fetch_index_prices",
        lambda symbol, *args: pd.DataFrame(index_rows),
    )

    result = feasibility.run_feasibility(
        {"as_of_date": "20231231", "index_symbol": "000300.SH"},
        {"start_date": "20170103", "validation_dir": str(tmp_path)},
    )

    assert result["data_version"] == "9.4.0"
    assert set(result["periods"]) == {"full", "development", "retrospective_diagnostic"}
    assert set(result["cost_sensitivity"]) == {"0", "15", "30"}
    assert result["qualitative_gate_backtested"] is False
    assert result["validation_level"] == "runnable"
    assert result["evidence_scope"] == "quantitative_retrospective_diagnostic"
    assert result["nav"]
    assert result["holdings_history"]
    assert result["rebalance"]
    assert "guarantee" not in result


def test_buy_blocked_at_limit_up_leaves_slot_in_cash():
    prices = pd.DataFrame(
        [
            {
                "date": "20260506",
                "symbol": "600000.SH",
                "open": 10.0,
                "close": 10.0,
                "tradable": True,
                "limit_up": True,
                "limit_down": False,
            }
        ]
    )
    signals = [
        {
            "signal_date": "20260430",
            "execution_date": "20260506",
            "symbols": ["600000.SH"],
        }
    ]

    result = feasibility.simulate_portfolio(prices, signals)

    assert result["holdings"].iloc[-1]["symbols"] == []
    assert result["holdings"].iloc[-1]["cash_weight"] == 1.0


def test_existing_position_add_action_is_executed_in_replay():
    prices = pd.DataFrame([
        {"date": "20260506", "symbol": "600000.SH", "open": 10.0, "close": 10.0, "tradable": True, "limit_up": False, "limit_down": False},
        {"date": "20270503", "symbol": "600000.SH", "open": 10.0, "close": 10.0, "tradable": True, "limit_up": False, "limit_down": False},
    ])
    signals = [
        {"signal_date": "20260430", "execution_date": "20260506", "actions": [{"target_id": "600000.SH", "review_action": "enter", "target_weight": 0.10}]},
        {"signal_date": "20270430", "execution_date": "20270503", "actions": [{"target_id": "600000.SH", "review_action": "add", "target_weight": 0.25}]},
    ]
    result = feasibility.simulate_portfolio(prices, signals)
    final = result["holdings"].iloc[-1]
    assert final["symbols"] == ["600000.SH"]
    assert final["weights"]["600000.SH"] == pytest.approx(0.25)


def test_restricted_sale_is_retried_on_following_trading_days():
    prices = pd.DataFrame(
        [
            {"date": "20260506", "symbol": "600000.SH", "open": 10, "close": 10, "tradable": True, "limit_up": False, "limit_down": False},
            {"date": "20270502", "symbol": "600000.SH", "open": 9, "close": 9, "tradable": True, "limit_up": False, "limit_down": True},
            {"date": "20270503", "symbol": "600000.SH", "open": 9, "close": 9, "tradable": True, "limit_up": False, "limit_down": False},
            {"date": "20270502", "symbol": "600001.SH", "open": 10, "close": 10, "tradable": True, "limit_up": False, "limit_down": False},
            {"date": "20270503", "symbol": "600001.SH", "open": 10, "close": 10, "tradable": True, "limit_up": False, "limit_down": False},
        ]
    )
    signals = [
        {"signal_date": "20260430", "execution_date": "20260506", "symbols": ["600000.SH"]},
        {"signal_date": "20270430", "execution_date": "20270502", "symbols": ["600001.SH"]},
    ]

    result = feasibility.simulate_portfolio(prices, signals)

    assert "600000.SH" in result["holdings"].iloc[-2]["pending_sells"]
    assert "600000.SH" not in result["holdings"].iloc[-1]["symbols"]
    assert result["holdings"].iloc[-1]["pending_sells"] == []


def test_offline_validation_artifacts_include_curve_holdings_and_disclosure(tmp_path):
    result = {
        "strategy_id": "Q44-BUFFETT-A-SHARE-V9",
        "data_version": "9.4.0",
        "as_of_date": "20260714",
        "start_date": "20170103",
        "economic_evidence": "mixed",
        "validation_level": "runnable",
        "engineering_gates": {"point_in_time_audit": True},
        "periods": {"retrospective_diagnostic": {"strategy_nav": {"cagr": 0.03, "max_drawdown": -0.2}}},
        "evidence_scope": "retrospective_diagnostic",
        "forward_validation": {"eligible": False, "sessions": 0},
        "cost_sensitivity_bps": {"0": {"cagr": 0.04}, "15": {"cagr": 0.03}, "30": {"cagr": 0.02}},
        "lookahead_audit": {"passed": True, "records": []},
        "nav_curve": [
            {"date": "20260506", "strategy_nav": 1.0, "benchmark_510300_nav": 1.0, "index_000300_nav": 1.0, "cash_511880_nav": 1.0, "cash_weight": 0.9, "stock_contributions": {}},
            {"date": "20260714", "strategy_nav": 1.1, "benchmark_510300_nav": 1.05, "index_000300_nav": 1.04, "cash_511880_nav": 1.01, "cash_weight": 0.9},
        ],
        "holdings_history": [{"date": "20260714", "symbols": ["600519.SH"], "cash_weight": 0.9, "pending_sells": []}],
        "rebalance_history": [{"signal_date": "20260430", "execution_date": "20260506", "turnover": 0.1}],
        "current_holdings": [{"target_id": "600519.SH", "target_weight": 0.1}],
        "current_cash_weight": 0.9,
        "attribution": {"stock_contributions": {"600519.SH": 0.1}, "cash_contribution": 0.01},
        "disclaimer": "Historical evidence is not a promise or guarantee of future returns and is not investment advice.",
    }

    paths = reporting.write_validation_artifacts(result, tmp_path)

    expected = {
        "nav",
        "holdings",
        "rebalances",
        "cost_sensitivity",
        "lookahead_audit",
        "lot_sensitivity",
            "attribution",
            "coverage_summary",
            "acceptance_report",
        "html_report",
            "preview",
            "portfolio_explanation",
        }
    assert set(paths) == expected
    assert all(path.exists() for path in paths.values())
    html = paths["html_report"].read_text(encoding="utf-8")
    assert "600519.SH" in html
    assert "不构成收益保证" in html


def test_empty_period_returns_null_metrics_instead_of_crashing():
    metrics = feasibility._performance(pd.DataFrame({"date": ["20220101"], "strategy_nav": [None]}), "strategy_nav")
    assert metrics["cagr"] is None
