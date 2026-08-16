from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from scripts import build, data_pipeline, panda_adapter, validation
from scripts.core import DATA_VERSION, InputValidationError
from scripts.scoring import evaluate_buffett_company, rank_buffett_candidates


def annual_history(symbol: str = "600000.SH", pe: float = 18.0) -> pd.DataFrame:
    rows = []
    for year in range(2015, 2026):
        rows.append(
            {
                "symbol": symbol,
                "year": year,
                "published_at": f"{year + 1}0331",
                "revision_id": f"{year}-final",
                "parent_net_profit": 20.0 + (year - 2015),
                "parent_equity": 100.0 + 10.0 * (year - 2015),
                "total_assets": 500.0 + 20.0 * (year - 2015),
                "gross_profit": 60.0,
                "revenue": 100.0,
                "gross_capex": 4.0,
                "operating_cash_flow": 28.0,
                "long_term_interest_bearing_debt": 10.0,
                "basic_eps": 5.0,
                "close": 5.0 * pe,
                "operating_profit": 26.0 + (year - 2015),
                "total_profit": 24.0 + (year - 2015),
                "income_tax": 4.0,
                "cash_equivalents": 8.0,
            }
        )
    return pd.DataFrame(rows)


def test_v6_input_is_a_share_only_and_breaks_old_market_contract():
    validation.validate_input({"as_of_date": "20260714", "symbols": ["600519.SH"]})
    validation.validate_input({"as_of_date": "20260714", "index_symbol": "000300.SH"})

    with pytest.raises(InputValidationError, match="markets"):
        validation.validate_input({"as_of_date": "20260714", "markets": ["cn"]})
    with pytest.raises(InputValidationError, match="不能同时"):
        validation.validate_input(
            {
                "as_of_date": "20260714",
                "symbols": ["600519.SH"],
                "index_symbol": "000300.SH",
            }
        )
    with pytest.raises(InputValidationError, match="A 股"):
        validation.validate_input({"as_of_date": "20260714", "symbols": ["0700.HK"]})


def test_environment_credentials_are_consumed_and_removed(monkeypatch):
    monkeypatch.setenv("PANDA_DATA_USERNAME", "fixture-user")
    monkeypatch.setenv("PANDA_DATA_PASSWORD", "fixture-secret")
    monkeypatch.setenv("PANDA_DATA_BASE_URL", "https://example.invalid")

    credentials = panda_adapter.consume_environment_credentials()

    assert credentials == ("fixture-user", "fixture-secret", "https://example.invalid")
    assert "PANDA_DATA_USERNAME" not in os.environ
    assert "PANDA_DATA_PASSWORD" not in os.environ
    assert "PANDA_DATA_BASE_URL" not in os.environ


def test_authentication_errors_never_include_secret(monkeypatch):
    panda_adapter.clear_process_credentials()
    monkeypatch.setenv("PANDA_DATA_USERNAME", "fixture-user")
    monkeypatch.setenv("PANDA_DATA_PASSWORD", "fixture-secret")
    with patch("panda_data.init_token", side_effect=RuntimeError("fixture-secret")):
        with pytest.raises(panda_adapter.PandaAuthenticationError) as exc_info:
            panda_adapter.ensure_authenticated()
    assert "fixture-secret" not in str(exc_info.value)
    panda_adapter.clear_process_credentials()


def test_clear_process_credentials_also_clears_sdk_token():
    with patch("panda_data.auth_manager.clear_auth") as clear_auth:
        panda_adapter.clear_process_credentials()
    clear_auth.assert_called_once_with()


def test_atomic_revision_selection_never_mixes_fields():
    frame = pd.DataFrame(
        [
            {
                "symbol": "600519.SH",
                "quarter": "2024q4",
                "date": "20250301",
                "is_n_income_attr_p": 100.0,
                "bs_total_hldr_eqy_exc_min_int": 500.0,
            },
            {
                "symbol": "600519.SH",
                "quarter": "2024q4",
                "date": "20250401",
                "is_n_income_attr_p": 110.0,
                "bs_total_hldr_eqy_exc_min_int": None,
            },
        ]
    )

    selected, conflicts = data_pipeline.select_atomic_annual_revisions(frame, "20250415")

    assert len(selected) == 1
    assert selected.iloc[0]["is_n_income_attr_p"] == 110.0
    assert pd.isna(selected.iloc[0]["bs_total_hldr_eqy_exc_min_int"])
    assert conflicts == []


def evaluate(history, industry="消费"):
    return evaluate_buffett_company(
        "600000.SH",
        history,
        industry=industry,
        audit_history=[{"year": 2025, "status": "unqualified"}],
        as_of_year=2025,
    )


def test_screen_uses_average_equity_five_year_capex_and_normalized_pe():
    result = evaluate(annual_history())

    assert result["metrics"]["roe_latest_pct"] == pytest.approx(30.0 / 195.0 * 100)
    assert result["metrics"]["capex_to_profit_5y"] == pytest.approx(20.0 / 140.0)
    assert result["metrics"]["normalized_pe"] == pytest.approx(18.0)
    serialized = json.dumps(result, ensure_ascii=False).lower()
    assert "owner_earnings_5y" in serialized
    assert "engineering proxies" in serialized
    assert result["decision"] == "research_candidate"


def test_latest_missing_profit_never_falls_back_to_old_year():
    history = annual_history()
    history.loc[history["year"] == 2025, "parent_net_profit"] = None

    result = evaluate(history)

    assert result["decision"] == "insufficient_data"
    assert result["metrics"]["long_term_debt_to_profit"] is None


def test_quality_pass_with_expensive_price_becomes_watchlist():
    result = evaluate(annual_history(pe=31.0))

    assert result["quality_score"] >= 70
    assert result["entry_eligible"] is False
    assert result["decision"] == "watchlist"


def test_bank_uses_roa_instead_of_leveraged_roe():
    history = annual_history()
    history["parent_net_profit"] = 8.0
    history["parent_equity"] = 20.0
    history["total_assets"] = 500.0

    history["close"] = 10.0
    result = evaluate(history, "银行")

    assert result["metrics"]["roa_latest_pct"] > 1.0
    assert result["special_case"] == "bank_roa"
    assert result["decision"] == "research_candidate"


def test_bank_failing_roa_is_rejected_and_missing_assets_are_insufficient():
    weak = annual_history()
    weak["parent_net_profit"] = 2.0
    weak["parent_equity"] = 10.0
    weak["total_assets"] = 500.0
    weak["close"] = 2.0
    rejected = evaluate(weak, "银行")
    assert rejected["decision"] == "reject"

    missing = annual_history()
    missing.loc[missing["year"] == 2025, "total_assets"] = None
    insufficient = evaluate(missing, "银行")
    assert insufficient["decision"] == "insufficient_data"


@pytest.mark.parametrize("industry", ["证券", "煤炭"])
def test_other_financial_and_cyclical_companies_are_manual_review(industry):
    result = evaluate(annual_history(), industry)
    assert result["decision"] == "manual_review"


def test_candidate_ranking_is_deterministic_and_has_no_weights():
    records = [
        {"target_id": "B.SZ", "decision": "research_candidate", "quality_score": 90, "cash_earnings_yield_proxy": .03},
        {"target_id": "A.SH", "decision": "research_candidate", "quality_score": 80, "cash_earnings_yield_proxy": .06},
    ]

    ranked = rank_buffett_candidates(records)

    assert [row["target_id"] for row in ranked] == ["B.SZ", "A.SH"]
    assert [row["priority_rank"] for row in ranked] == [1, 2]
    assert "weight" not in json.dumps(ranked).lower()


def test_run_uses_v8_contract_and_never_calls_non_a_share_apis():
    raw = annual_history("600519.SH").rename(
        columns={
            "year": "financial_year",
            "published_at": "date",
            "parent_net_profit": "is_n_income_attr_p",
            "parent_equity": "bs_total_hldr_eqy_exc_min_int",
            "total_assets": "bs_total_assets",
            "gross_profit": "is_gross_profit",
            "revenue": "is_revenue",
            "gross_capex": "cfs_cash_paid_asset",
            "operating_cash_flow": "cfs_net_cashflow_operate",
            "long_term_interest_bearing_debt": "bs_longterm_loan",
            "basic_eps": "is_basic_eps",
            "operating_profit": "is_operate_profit",
            "total_profit": "is_total_profit",
            "income_tax": "is_income_tax",
            "cash_equivalents": "cfs_end_cash_equiv",
        }
    )
    raw["quarter"] = raw["financial_year"].astype(str) + "q4"
    prices = pd.DataFrame([{"symbol": "600519.SH", "date": "20260713", "close": 90.0}])
    details = pd.DataFrame([{"symbol": "600519.SH", "industry_name": "消费"}])
    calls = []

    def fake_fetch(name, **kwargs):
        calls.append(name)
        if name == "get_fina_reports":
            return raw
        if name == "get_stock_daily":
            return prices
        if name == "get_stock_detail":
            return details
        if name == "get_industry_constituents":
            return pd.DataFrame([{"stock_symbol": "600519.SH", "l1_code": "801120", "in_date": "20000101", "out_date": None}])
        if name == "get_industry_detail":
            return pd.DataFrame([{"industry_code": "801120", "industry_name": "食品饮料"}])
        if name == "get_trade_cal":
            return pd.DataFrame([{"nature_date": "20260430", "is_trade": 1}, {"nature_date": "20260506", "is_trade": 1}])
        if name == "get_audit_opinion":
            return pd.DataFrame([{"symbol": "600519.SH", "quarter": "2025q4", "date": "20260320", "opinion": "unqualified_opinion"}])
        raise AssertionError(name)

    with patch.object(data_pipeline, "fetch", side_effect=fake_fetch), patch.object(
        build, "sdk_version", return_value="0.0.12"
    ):
        result = build.run({"as_of_date": "20260714", "symbols": ["600519.SH"]})

    assert result["data_version"] == "9.4.0"
    assert result["source"]["market"] == "cn"
    assert result["records"][0]["result_type"] == "buffett_research_candidate"
    assert set(calls) <= {
        "get_fina_reports",
        "get_stock_daily",
        "get_stock_detail",
        "get_industry_constituents",
        "get_industry_detail",
        "get_audit_opinion",
        "get_trade_cal",
    }
    assert result["portfolio"]["holdings"] == []
    assert result["portfolio"]["cash_weight"] == 1.0
    assert "orders" not in result


def test_v8_production_frame_and_failed_write_preserve_existing_file(tmp_path):
    assert DATA_VERSION == "9.4.0"
    record = {
        "target_id": "600519.SH",
        "result_type": "buffett_research_candidate",
        "result_value": "research_candidate",
        "source_data_date": "20260713",
        "actual_source_date": "20260713",
        "coverage_status": "complete",
        "payload": {"decision": "research_candidate"},
    }
    frame = panda_adapter.build_production_frame(
        build_id="Q44",
        build_name="A 股巴菲特研究候选",
        trade_date="20260714",
        records=[record],
        data_version="9.4.0",
    )
    assert set(frame["schema_version"]) == {"3.0.0"}
    assert set(frame["target_id"]) == {"600519.SH"}

    output = tmp_path / "database.parquet"
    output.write_bytes(b"existing")
    with patch.object(pd.DataFrame, "to_parquet", side_effect=RuntimeError("write failed")):
        with pytest.raises(RuntimeError, match="write failed"):
            panda_adapter.write_production(frame, output, replace_all=True)
    assert output.read_bytes() == b"existing"


def test_replace_all_production_preserves_research_priority_order(tmp_path):
    records = []
    for symbol, rank in [("600002.SH", 1), ("600001.SH", 2)]:
        records.append(
            {
                "target_id": symbol,
                "result_type": "buffett_research_candidate",
                "result_value": "research_candidate",
                "source_data_date": "20260713",
                "actual_source_date": "20260713",
                "coverage_status": "complete",
                "payload": {
                    "decision": "research_candidate",
                    "priority_rank": rank,
                },
            }
        )
    frame = panda_adapter.build_production_frame(
        build_id="Q44",
        build_name="A 股巴菲特研究候选",
        trade_date="20260714",
        records=records,
        data_version="6.0.0",
    )

    output = tmp_path / "database.parquet"
    panda_adapter.write_production(frame, output, replace_all=True)
    written = pd.read_parquet(output)

    assert written["target_id"].tolist() == ["600002.SH", "600001.SH"]
