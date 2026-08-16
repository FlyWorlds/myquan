from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts import build, data_pipeline, panda_adapter
from scripts.core import DATA_VERSION
from scripts.feasibility import (
    classify_economic_evidence,
    make_annual_schedule,
    simulate_portfolio,
)
from scripts.portfolio import build_portfolio
from scripts.portfolio import _candidate_key


def candidate(symbol: str, pe: float, roe_floor: float = 15.0) -> dict:
    return {
        "target_id": symbol,
        "decision": "research_candidate",
        "priority_rank": None,
        "quality_score": 90.0 - pe / 100,
        "cash_earnings_yield_proxy": 0.05,
        "normalized_pe": pe,
        "entry_eligible": True,
        "qualitative_verdict": "approve",
        "qualitative_score": 90.0,
        "qualitative_confidence": 90.0,
        "valuation_score": 80.0,
        "conviction_score": 86.0,
        "hold_status": "healthy",
        "sell_triggers": [],
        "industry": "",
        "special_case": None,
        "metrics": {
            "pe_lyr": pe,
            "roe_ten_year_floor_pct": roe_floor,
            "capex_to_profit_5y": 0.1,
            "gross_margin_std_pct_points": 2.0,
        },
    }


def test_v8_portfolio_uses_concentrated_tiers_and_keeps_unfilled_cash():
    records = [candidate(f"6000{i:02d}.SH", 10 + i) for i in range(3)]
    records += [{"target_id": "000001.SZ", "decision": "watchlist", "metrics": {"pe_lyr": 9}}]

    portfolio = build_portfolio(records, signal_date="20260430", execution_date="20260506")

    assert DATA_VERSION == "9.4.0"
    assert [row["target_id"] for row in portfolio["holdings"]] == [
        "600000.SH",
        "600001.SH",
        "600002.SH",
    ]
    assert [row["target_weight"] for row in portfolio["holdings"]] == [0.2, 0.2, 0.2]
    assert portfolio["cash_weight"] == pytest.approx(0.4)
    assert portfolio["slot_count"] == 8
    assert portfolio["signal_date"] == "20260430"
    assert portfolio["execution_date"] == "20260506"


def test_portfolio_candidate_order_is_quality_first_not_cheapest_first():
    strong = candidate("600010.SH", 24)
    cheap = candidate("600011.SH", 8)
    strong["quality_score"] = 85.0
    strong["valuation_score"] = 60.0
    strong["metrics"].update({"roe_floor_pct": 13.0, "roic_proxy_floor_pct": 10.0})
    cheap["quality_score"] = 84.0
    cheap["valuation_score"] = 100.0
    cheap["metrics"].update({"roe_floor_pct": 7.0, "roic_proxy_floor_pct": 4.0})
    assert sorted([strong, cheap], key=_candidate_key)[0]["target_id"] == "600010.SH"


def test_v8_portfolio_optional_capital_outputs_100_share_lots():
    portfolio = build_portfolio(
        [candidate("600519.SH", 20)],
        signal_date="20260430",
        execution_date="20260506",
        capital=1_000_000,
        execution_prices={"600519.SH": 1600.0},
    )

    holding = portfolio["holdings"][0]
    assert holding["reference_quantity"] == 100
    assert holding["reference_value"] == 160_000.0
    assert portfolio["cash_amount"] == 840_000
    assert portfolio["lot_size"] == 100


def test_historical_industry_membership_obeys_effective_interval():
    frame = pd.DataFrame(
        [
            {"symbol": "600000.SH", "industry_name": "银行", "in_date": "20100101", "out_date": "20200101"},
            {"symbol": "600000.SH", "industry_name": "非银金融", "in_date": "20200101", "out_date": None},
        ]
    )

    assert data_pipeline.historical_industry_map(frame, "20191231")["600000.SH"] == "银行"
    assert data_pipeline.historical_industry_map(frame, "20200101")["600000.SH"] == "非银金融"


def test_raw_limit_prices_are_compared_with_open_not_cast_to_boolean(monkeypatch):
    adjusted = pd.DataFrame(
        [
            {"symbol": "600000.SH", "date": "20260506", "open": 100.0, "close": 100.0, "volume": 1},
            {"symbol": "600000.SH", "date": "20260507", "open": 110.0, "close": 110.0, "volume": 1},
        ]
    )
    raw = pd.DataFrame(
        [
            {"symbol": "600000.SH", "date": "20260506", "open": 10.0, "pre_close": 10.0, "volume": 1, "limit_up": 11.0, "limit_down": 9.0},
            {"symbol": "600000.SH", "date": "20260507", "open": 11.0, "pre_close": 10.0, "volume": 1, "limit_up": 11.0, "limit_down": 9.0},
        ]
    )
    monkeypatch.setattr(
        data_pipeline,
        "fetch",
        lambda name, **kwargs: adjusted if name == "get_stock_daily_post" else raw,
    )

    result = data_pipeline.fetch_stock_backtest_prices(
        ["600000.SH"], "20260506", "20260507"
    )

    assert result["limit_up"].tolist() == [False, True]
    assert result["limit_down"].tolist() == [False, False]


def test_annual_schedule_signals_at_april_30_close_and_executes_next_session():
    calendar = pd.DataFrame(
        {
            "date": ["20260429", "20260430", "20260501", "20260506"],
            "is_open": [1, 1, 0, 1],
        }
    )

    assert make_annual_schedule(calendar, "20260101", "20261231") == [
        {"year": 2026, "signal_date": "20260430", "execution_date": "20260506"}
    ]


def test_fractional_backtest_applies_t_plus_one_cost_and_cash_slots():
    prices = pd.DataFrame(
        [
            {"date": "20260506", "symbol": "600000.SH", "open": 10.0, "close": 10.0, "tradable": True},
            {"date": "20260507", "symbol": "600000.SH", "open": 11.0, "close": 11.0, "tradable": True},
        ]
    )
    signals = [{"signal_date": "20260430", "execution_date": "20260506", "symbols": ["600000.SH"]}]

    result = simulate_portfolio(prices, signals, cost_bps=15)

    first = result["nav"].iloc[0]
    last = result["nav"].iloc[-1]
    assert first["strategy_nav"] == pytest.approx(1 - 0.2 * 0.0015)
    assert last["strategy_nav"] == pytest.approx((1 - 0.2 * 0.0015) * 1.02)
    assert result["holdings"].iloc[0]["cash_weight"] == pytest.approx(0.8)


@pytest.mark.parametrize(
    ("strategy", "benchmark", "strategy_mdd", "benchmark_mdd", "expected"),
    [
        (0.08, 0.05, -0.20, -0.18, "supported"),
        (0.03, 0.05, -0.20, -0.18, "mixed"),
        (0.00, -0.03, -0.10, -0.20, "unsupported"),
    ],
)
def test_economic_evidence_gate(strategy, benchmark, strategy_mdd, benchmark_mdd, expected):
    assert classify_economic_evidence(strategy, benchmark, strategy_mdd, benchmark_mdd) == expected


def test_all_cash_cannot_be_supported_even_if_cash_outperforms():
    assert classify_economic_evidence(
        0.03, 0.01, -0.001, -0.30, has_equity_exposure=False
    ) == "unsupported"


def test_cash_dominant_return_is_mixed_not_selection_supported():
    assert classify_economic_evidence(
        0.08,
        0.05,
        -0.20,
        -0.18,
        cash_contribution=0.20,
        stock_contribution=0.04,
    ) == "mixed"


def test_secondary_investable_benchmark_failure_is_not_supported():
    assert classify_economic_evidence(
        0.05,
        0.02,
        -0.10,
        -0.30,
        secondary_benchmark_cagr=0.06,
        secondary_benchmark_max_drawdown=-0.25,
    ) == "mixed"


def test_production_frame_supports_four_v8_result_types_and_string_values():
    records = []
    for result_type, target_id, value in [
        ("buffett_research_candidate", "600519.SH", "research_candidate"),
        ("portfolio_target_weight", "600519.SH", 0.1),
        ("portfolio_summary", "Q44-PORTFOLIO", 0.9),
        ("strategy_validation", "Q44-VALIDATION", "runnable"),
    ]:
        records.append(
            {
                "target_id": target_id,
                "result_type": result_type,
                "result_value": value,
                "source_data_date": "20260714",
                "actual_source_date": "20260714",
                "coverage_status": "complete",
                "payload": {"value": value},
            }
        )

    frame = panda_adapter.build_production_frame(
        build_id="Q44",
        build_name="A-share Buffett portfolio",
        trade_date="20260714",
        records=records,
        data_version="9.4.0",
    )

    assert frame.shape[1] == 14
    assert set(frame["result_type"]) == {
        "buffett_research_candidate",
        "portfolio_target_weight",
        "portfolio_summary",
        "strategy_validation",
    }
    assert all(isinstance(value, str) for value in frame["result_value"])
    assert json.loads(frame.loc[frame["result_type"] == "portfolio_target_weight", "result_json"].iloc[0])["value"] == 0.1


def test_build_config_accepts_capital_and_rejects_nonpositive_capital():
    build._validate_config({"capital": 1_000_000})
    with pytest.raises(ValueError, match="capital"):
        build._validate_config({"capital": 0})


def test_build_returns_derived_portfolio_without_automatic_order(monkeypatch):
    history = pd.DataFrame(
        [
            {
                "symbol": "600519.SH",
                "year": year,
                "published_at": f"{year + 1}0331",
                "parent_net_profit": 30.0,
                "parent_equity": 100.0,
                "total_assets": 300.0,
                "gross_profit": 60.0,
                "revenue": 100.0,
                "gross_capex": 2.0,
                "operating_cash_flow": 35.0,
                "long_term_interest_bearing_debt": 10.0,
                "basic_eps": 5.0,
                "close": 100.0,
                "operating_profit": 36.0,
                "total_profit": 34.0,
                "income_tax": 5.0,
                "cash_equivalents": 10.0,
            }
            for year in range(2015, 2026)
        ]
    )
    monkeypatch.setattr(data_pipeline, "fetch_financial_history", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(data_pipeline, "select_atomic_annual_revisions", lambda *args: (pd.DataFrame(), []))
    monkeypatch.setattr(data_pipeline, "fetch_prices", lambda *args: pd.DataFrame())
    monkeypatch.setattr(data_pipeline, "normalize_annual_history", lambda *args: history)
    monkeypatch.setattr(
        data_pipeline,
        "fetch_historical_industries",
        lambda *args: pd.DataFrame(
            [{"stock_symbol": "600519.SH", "industry_name": "食品饮料", "in_date": "20000101", "out_date": None}]
        ),
    )
    monkeypatch.setattr(
        data_pipeline,
        "fetch_audit_histories",
        lambda symbols, **kwargs: {
            symbol: [{"year": 2025, "status": "unqualified"}] for symbol in symbols
        },
    )
    monkeypatch.setattr(data_pipeline, "fetch_execution_prices", lambda *args: {"600519.SH": 100.0})
    monkeypatch.setattr(
        data_pipeline,
        "fetch_trade_calendar",
        lambda *args: pd.DataFrame(
            {"date": ["20260430", "20260506"], "is_open": [1, 1]}
        ),
    )
    monkeypatch.setattr(build, "sdk_version", lambda: "0.0.12")

    output = build.run(
        {"as_of_date": "20260714", "symbols": ["600519.SH"]},
        {"capital": 1_000_000},
    )

    assert output["portfolio"]["strategy_id"] == "Q44-BUFFETT-A-SHARE-V9"
    assert output["portfolio"]["signal_date"] == "20260714"
    assert output["portfolio"]["execution_date"] == "20260714"
    assert output["portfolio"]["holdings"] == []
    assert output["portfolio"]["cash_weight"] == 1.0
    assert "orders" not in output


def test_v8_first_write_rebuilds_old_versions_then_upserts_idempotently(tmp_path):
    output = tmp_path / "database.parquet"
    old = panda_adapter.build_production_frame(
        build_id="Q44",
        build_name="old",
        trade_date="20250714",
        records=[
            {
                "target_id": "600000.SH",
                "result_type": "buffett_research_candidate",
                "result_value": "reject",
                "source_data_date": "20250714",
                "actual_source_date": "20250714",
                "coverage_status": "complete",
                "payload": {"old": True},
            }
        ],
        data_version="6.0.0",
    )
    old.to_parquet(output, index=False)

    def v8_frame(trade_date: str, value: str) -> pd.DataFrame:
        return panda_adapter.build_production_frame(
            build_id="Q44",
            build_name="v8",
            trade_date=trade_date,
            records=[
                {
                    "target_id": "CASH.CNY",
                    "result_type": "portfolio_target_weight",
                    "result_value": value,
                    "source_data_date": trade_date,
                    "actual_source_date": trade_date,
                    "coverage_status": "complete",
                    "payload": {"weight": float(value)},
                }
            ],
            data_version="9.4.0",
        )

    panda_adapter.write_versioned_production(v8_frame("20260506", "0.9"), output, "9.4.0")
    assert set(pd.read_parquet(output)["data_version"]) == {"9.4.0"}

    panda_adapter.write_versioned_production(v8_frame("20270506", "0.8"), output, "9.4.0")
    panda_adapter.write_versioned_production(v8_frame("20270506", "0.7"), output, "9.4.0")
    written = pd.read_parquet(output).sort_values("trade_date")
    assert len(written) == 2
    assert written.iloc[-1]["result_value"] == "0.7"
