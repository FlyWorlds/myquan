from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.core import DATA_VERSION
from scripts.feasibility import simulate_portfolio
from scripts.portfolio import (
    build_portfolio,
    load_materialized_portfolio,
    load_portfolio_state,
    mark_to_market_state,
)
from scripts.scoring import evaluate_buffett_company, rank_buffett_candidates


def quality_history(symbol: str = "600001.SH", *, gross_margin: float = 0.30) -> pd.DataFrame:
    rows = []
    for year in range(2015, 2026):
        step = year - 2015
        profit = 20.0 * (1.08**step)
        eps = 2.0 * (1.08**step)
        rows.append(
            {
                "symbol": symbol,
                "year": year,
                "published_at": f"{year + 1}0331",
                "parent_net_profit": profit,
                "parent_equity": 100.0 * (1.06**step),
                "total_assets": 180.0 * (1.05**step),
                "gross_profit": gross_margin * 100.0,
                "revenue": 100.0,
                "gross_capex": 3.0,
                "operating_cash_flow": profit * 1.05,
                "long_term_interest_bearing_debt": 8.0,
                "basic_eps": eps,
                "close": eps * 20.0,
                "operating_profit": profit * 1.20,
                "total_profit": profit * 1.15,
                "income_tax": profit * 0.15,
                "cash_equivalents": 10.0,
            }
        )
    return pd.DataFrame(rows)


def record(
    symbol: str,
    quality: float,
    *,
    industry: str = "食品饮料",
    bank: bool = False,
    entry: bool = True,
    hold_status: str = "healthy",
    sell_triggers: list[str] | None = None,
) -> dict:
    return {
        "target_id": symbol,
        "decision": "research_candidate" if entry else "watchlist",
        "quality_score": quality,
        "cash_earnings_yield_proxy": 0.04,
        "normalized_pe": 20.0,
        "entry_eligible": entry,
        "qualitative_verdict": "approve" if entry else "qualitative_pending",
        "qualitative_score": quality,
        "qualitative_confidence": 90.0,
        "valuation_score": 80.0,
        "conviction_score": quality,
        "industry": "银行" if bank else industry,
        "special_case": "bank_roa" if bank else None,
        "hold_status": hold_status,
        "sell_triggers": sell_triggers or [],
        "metrics": {"pe_lyr": 20.0},
    }


def test_v8_quality_scoring_replaces_universal_40pct_margin_gate():
    result = evaluate_buffett_company(
        "600001.SH",
        quality_history(gross_margin=0.30),
        industry="食品饮料",
        audit_history=[{"year": 2025, "status": "unqualified"}],
        as_of_year=2025,
    )

    assert DATA_VERSION == "9.4.0"
    assert result["metrics"]["gross_margin_latest_pct"] == pytest.approx(30.0)
    assert result["quality_score"] >= 70
    assert result["entry_eligible"] is True
    assert result["decision"] == "research_candidate"
    assert result["moat_score"] <= 40
    assert result["capital_allocation_score"] <= 30
    assert result["financial_strength_score"] <= 20
    assert result["missing_score_weight"] <= 20
    assert result["metrics"]["roic_proxy_median_pct"] is not None
    assert result["metrics"]["roic_proxy_latest_pct"] is not None
    assert result["metrics"]["incremental_roic_proxy_pct"] is not None


def test_incremental_roic_missing_reduces_capital_allocation_coverage():
    history = quality_history()
    history.loc[history["year"] == 2021, "operating_profit"] = None
    result = evaluate_buffett_company(
        "600001.SH",
        history,
        industry="食品饮料",
        audit_history=[{"year": 2025, "status": "unqualified"}],
        as_of_year=2025,
    )
    assert result["metrics"]["incremental_roic_proxy_pct"] is None
    assert result["missing_score_weight"] >= 5


def test_v8_normalized_valuation_and_cash_yield_are_explicit():
    result = evaluate_buffett_company(
        "600001.SH",
        quality_history(),
        industry="食品饮料",
        audit_history=[{"year": 2024, "status": "unqualified"}],
        as_of_year=2025,
    )

    assert result["audit_freshness"] == "audit_lagged"
    assert result["metrics"]["normalized_eps"] > 0
    assert result["normalized_pe"] <= 30
    assert result["cash_earnings_yield_proxy"] >= 0.03


def test_owner_earnings_persistence_is_visible_and_warns_when_capex_consumes_cash():
    history = quality_history()
    # Keep operating cash flow positive while making two of the latest five
    # years consume all operating cash after long-term asset purchases.
    latest_years = history["year"] >= 2023
    history.loc[latest_years & history["year"].isin([2023, 2025]), "gross_capex"] = history.loc[
        latest_years & history["year"].isin([2023, 2025]), "operating_cash_flow"
    ]
    result = evaluate_buffett_company(
        "600001.SH",
        history,
        industry="食品饮料",
        audit_history=[{"year": 2025, "status": "unqualified"}],
        as_of_year=2025,
    )

    assert result["metrics"]["owner_earnings_positive_year_ratio"] == pytest.approx(0.6)
    assert result["metrics"]["owner_earnings_positive_year_ratio_3y"] == pytest.approx(1 / 3)
    assert result["hold_status"] == "warning"
    assert result["entry_eligible"] is False


def test_v8_quality_ranking_is_not_low_pe_ranking():
    high_quality = record("600001.SH", 92)
    high_quality["normalized_pe"] = 28
    cheap = record("600002.SH", 74)
    cheap["normalized_pe"] = 10

    ranked = rank_buffett_candidates([cheap, high_quality])

    assert [row["target_id"] for row in ranked] == ["600001.SH", "600002.SH"]


def test_v8_missing_scoring_evidence_over_20_is_insufficient():
    history = quality_history().drop(
        columns=["operating_profit", "total_profit", "income_tax", "cash_equivalents"]
    )
    history["operating_cash_flow"] = pd.NA

    result = evaluate_buffett_company(
        "600001.SH",
        history,
        industry="食品饮料",
        audit_history=[{"year": 2025, "status": "unqualified"}],
        as_of_year=2025,
    )

    assert result["missing_score_weight"] > 20
    assert result["decision"] == "insufficient_data"
    assert result["metrics"]["roic_proxy_median_pct"] is None


def test_v8_concentrated_weights_bank_and_industry_caps():
    records = [
        record("600001.SH", 99, industry="食品饮料"),
        record("600002.SH", 98, industry="食品饮料"),
        record("600003.SH", 97, industry="食品饮料"),
        record("600004.SH", 96, industry="医药生物"),
        record("600005.SH", 95, bank=True),
        record("600006.SH", 94, bank=True),
        record("600007.SH", 93, industry="家用电器"),
        record("600008.SH", 92, industry="汽车"),
        record("600009.SH", 91, industry="公用事业"),
    ]

    portfolio = build_portfolio(records, signal_date="20260430", execution_date="20260506")

    assert portfolio["strategy_id"] == "Q44-BUFFETT-A-SHARE-V9"
    assert len(portfolio["holdings"]) <= 8
    assert max(row["policy_weight"] for row in portfolio["holdings"]) <= 0.25
    assert sum(row["policy_weight"] for row in portfolio["holdings"] if row["special_case"] == "bank_roa") <= 0.15
    assert len([row for row in portfolio["holdings"] if row["special_case"] == "bank_roa"]) <= 1
    food_weight = sum(row["policy_weight"] for row in portfolio["holdings"] if row["industry"] == "食品饮料")
    assert food_weight <= 0.30
    assert portfolio["cash_weight"] == pytest.approx(
        1 - sum(row["policy_weight"] for row in portfolio["holdings"])
    )


def test_v8_expensive_existing_holding_is_retained_without_rebalancing():
    prior = {
        "holdings": [
            {
                "target_id": "600001.SH",
                "holding_since": "20220505",
                "annual_warning_count": 0,
                "policy_weight": 0.20,
                "actual_weight": 0.27,
                "industry": "食品饮料",
                "special_case": None,
            }
        ]
    }
    expensive = record("600001.SH", 88, entry=False)

    portfolio = build_portfolio(
        [expensive],
        signal_date="20260430",
        execution_date="20260506",
        prior_state=prior,
    )

    holding = portfolio["holdings"][0]
    assert holding["review_action"] == "hold"
    assert holding["actual_weight"] == pytest.approx(0.27)
    assert holding["annual_warning_count"] == 0
    assert holding["qualitative_score"] == 88
    assert holding["valuation_score"] == 80.0
    assert holding["conviction_score"] == 88
    assert holding["policy_ceiling"] == pytest.approx(0.20)
    assert portfolio["transitions"][0]["reason"] == "valuation_does_not_force_sale"


def test_v8_two_consecutive_warnings_exit_but_one_warning_holds():
    base = {
        "target_id": "600001.SH",
        "holding_since": "20220505",
        "policy_weight": 0.20,
        "actual_weight": 0.20,
        "industry": "食品饮料",
        "special_case": None,
    }
    warning = record("600001.SH", 60, entry=False, hold_status="warning")

    first = build_portfolio(
        [warning],
        signal_date="20250430",
        execution_date="20250506",
        prior_state={"holdings": [{**base, "annual_warning_count": 0}]},
    )
    second = build_portfolio(
        [warning],
        signal_date="20260430",
        execution_date="20260506",
        prior_state={"holdings": first["holdings"]},
    )

    assert first["holdings"][0]["review_action"] == "warning_hold"
    assert first["holdings"][0]["annual_warning_count"] == 1
    assert second["holdings"] == []
    assert second["transitions"][0]["review_action"] == "exit"


def test_v9_quality_confirmation_can_add_existing_position_to_policy_ceiling():
    prior = {
        "holdings": [{
            "target_id": "600001.SH",
            "holding_since": "20220505",
            "policy_weight": 0.10,
            "actual_weight": 0.10,
            "industry": "食品饮料",
            "special_case": None,
            "conviction_score": 75.0,
        }]
    }
    result = build_portfolio(
        [record("600001.SH", 95.0)],
        signal_date="20260719",
        execution_date="20260720",
        prior_state=prior,
    )
    assert result["holdings"][0]["policy_weight"] == pytest.approx(0.25)
    assert any(item["review_action"] == "add" for item in result["transitions"])


def test_v9_missing_refresh_does_not_force_sell():
    prior = {
        "holdings": [{
            "target_id": "600001.SH",
            "holding_since": "20220505",
            "policy_weight": 0.20,
            "actual_weight": 0.20,
            "annual_warning_count": 1,
            "industry": "食品饮料",
        }]
    }
    portfolio = build_portfolio(
        [], signal_date="20260430", execution_date="20260506", prior_state=prior
    )
    assert [row["target_id"] for row in portfolio["holdings"]] == ["600001.SH"]
    assert portfolio["holdings"][0]["review_action"] == "warning_hold"
    assert portfolio["transitions"][0]["review_action"] == "warning_hold"
    assert portfolio["transitions"][0]["reason"] == "current_evidence_missing_no_forced_exit"


def test_v8_state_loader_never_reads_future_rows(tmp_path):
    rows = []
    for trade_date, symbol in [("20250506", "600001.SH"), ("20270506", "600002.SH")]:
        rows.append(
            {
                "trade_date": trade_date,
                "build_id": "Q44",
                "build_name": "v8",
                "target_id": symbol,
                "result_type": "portfolio_target_weight",
                "result_value": "0.2000000000",
                "result_json": json.dumps(
                    {
                        "target_id": symbol,
                        "policy_weight": 0.2,
                        "actual_weight": 0.2,
                        "holding_since": trade_date,
                        "annual_warning_count": 0,
                        "industry": "食品饮料",
                        "special_case": None,
                    }
                ),
                "source_data_date": trade_date,
                "data_version": "9.4.0",
                "update_time": "2026-01-01T00:00:00Z",
                "schema_version": "3.0.0",
                "run_id": "fixture",
                "coverage_status": "complete",
                "actual_source_date": trade_date,
            }
        )
    path = tmp_path / "database.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)

    state = load_portfolio_state(path, signal_date="20260430")

    assert [row["target_id"] for row in state["holdings"]] == ["600001.SH"]
    assert state["state_origin"] == "production"


def test_v8_same_year_materialized_review_is_idempotently_reused(tmp_path):
    payload = {
        "strategy_id": "Q44-BUFFETT-A-SHARE-V9",
        "signal_date": "20260430",
        "execution_date": "20260506",
        "holdings": [{"target_id": "600001.SH", "actual_weight": 0.8}],
        "cash_weight": 0.2,
    }
    path = tmp_path / "database.parquet"
    pd.DataFrame(
        [
            {
                "trade_date": "20260506",
                "data_version": "9.4.0",
                "result_type": "portfolio_summary",
                "result_json": json.dumps(payload),
            }
        ]
    ).to_parquet(path, index=False)

    result = load_materialized_portfolio(
        path, signal_date="20260430", execution_date="20260506"
    )

    assert result is not None
    assert result["holdings"][0]["actual_weight"] == 0.8
    assert result["state_origin"] == "materialized_current_review"


def test_v8_main_cash_leg_earns_511880_return():
    stock_prices = pd.DataFrame(
        [
            {"date": "20260506", "symbol": "600001.SH", "open": 10, "close": 10, "tradable": True},
            {"date": "20260507", "symbol": "600001.SH", "open": 10, "close": 10, "tradable": True},
        ]
    )
    cash_prices = pd.DataFrame(
        [
            {"date": "20260506", "open": 100, "close": 100},
            {"date": "20260507", "open": 110, "close": 110},
        ]
    )

    result = simulate_portfolio(stock_prices, [], cash_prices=cash_prices)

    assert result["nav"].iloc[-1]["strategy_nav"] == pytest.approx(1.10)
    assert result["nav"].iloc[-1]["cash_contribution"] > 0


def test_v8_bank_uses_dedicated_score_and_entry_valuation():
    history = quality_history("600000.SH")
    history["close"] = history["basic_eps"] * 5.0
    result = evaluate_buffett_company(
        "600000.SH",
        history,
        industry="银行",
        audit_history=[{"year": 2025, "status": "unqualified"}],
        as_of_year=2025,
    )

    assert result["special_case"] == "bank_roa"
    assert result["quality_score"] >= 75
    assert result["metrics"]["pb"] <= 1.8
    assert result["entry_eligible"] is True


def test_v9_bank_requires_a_minimum_roa_floor_not_only_a_strong_median():
    history = quality_history("600000.SH")
    weak_year = history["year"].eq(2016)
    history.loc[weak_year, "parent_net_profit"] = 0.5
    history.loc[weak_year, "operating_profit"] = 0.6
    history.loc[weak_year, "total_profit"] = 0.55
    history.loc[weak_year, "income_tax"] = 0.05
    history.loc[weak_year, "basic_eps"] = 0.05
    history.loc[weak_year, "close"] = 0.25
    result = evaluate_buffett_company(
        "600000.SH",
        history,
        industry="银行",
        audit_history=[{"year": 2025, "status": "unqualified"}],
        as_of_year=2025,
    )

    assert result["metrics"]["roa_floor_pct"] < 0.6
    assert result["decision"] != "research_candidate"


def test_v8_fundamental_audit_trigger_exits_immediately():
    prior = {
        "holdings": [
            {
                "target_id": "600001.SH",
                "holding_since": "20220505",
                "annual_warning_count": 0,
                "policy_weight": 0.2,
                "actual_weight": 0.2,
                "industry": "食品饮料",
            }
        ]
    }
    damaged = record("600001.SH", 85, entry=False, sell_triggers=["audit_opinion"])

    result = build_portfolio(
        [damaged], signal_date="20260430", execution_date="20260506", prior_state=prior
    )

    assert result["holdings"] == []
    assert result["transitions"][0]["review_action"] == "exit"


def test_v8_mark_to_market_and_risk_trim_preserve_drift_semantics():
    state = {
        "holdings": [
            {
                "target_id": "600001.SH",
                "holding_since": "20220505",
                "policy_weight": 0.2,
                "actual_weight": 0.2,
                "industry": "食品饮料",
            }
        ],
        "state_origin": "production",
    }
    marked = mark_to_market_state(state, {"600001.SH": 2.0}, cash_return_factor=1.0)
    assert marked["holdings"][0]["actual_weight"] == pytest.approx(1 / 3)

    portfolio = build_portfolio(
        [record("600001.SH", 90, entry=False)],
        signal_date="20260430",
        execution_date="20260506",
        prior_state=marked,
        qualitative_required=True,
    )
    assert portfolio["holdings"][0]["review_action"] == "risk_trim"
    assert portfolio["holdings"][0]["actual_weight"] == pytest.approx(0.25)
