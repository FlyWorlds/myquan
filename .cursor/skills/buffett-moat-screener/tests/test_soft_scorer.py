from __future__ import annotations

import pandas as pd
import pytest

from scripts import backtest_runner, build
from scripts.soft_scorer import score_payload


def _metrics() -> dict[str, float]:
    return {
        "roe_mean_pct": 18.0,
        "gross_margin_mean_5y_pct": 50.0,
        "gross_margin_std_5y_pct_points": 0.0,
        "capex_to_profit_5y": 0.10,
        "operating_margin_mean_5y_pct": 25.0,
        "current_pe": 10.0,
        "roa_median_pct": 1.2,
        "roa_floor_pct": 1.0,
        "pb": 0.6,
    }


def test_soft_score_matches_five_requested_anchor_curves():
    result = score_payload({"target_id": "600001.SH", "metrics": _metrics()})
    assert result["total_score"] == pytest.approx(100.0)
    assert result["coverage_ratio"] == pytest.approx(1.0)
    assert [row["base_weight"] for row in result["dimensions"]] == [0.30, 0.25, 0.15, 0.15, 0.15]


def test_bank_gross_margin_is_na_and_weights_are_renormalized():
    result = score_payload({"target_id": "600036.SH", "special_case": "bank_roa", "metrics": _metrics()})
    dimensions = {row["name"]: row for row in result["dimensions"]}
    assert dimensions["gross_margin"]["applicable"] is False
    assert dimensions["gross_margin"]["score"] is None
    assert dimensions["gross_margin"]["effective_weight"] == 0.0
    assert dimensions["roe"]["effective_weight"] == pytest.approx(0.40)
    assert sum(row["effective_weight"] for row in result["dimensions"]) == pytest.approx(1.0)


def test_missing_ordinary_metric_is_not_awarded_neutral_points():
    metrics = _metrics()
    metrics["gross_margin_mean_5y_pct"] = None
    metrics["gross_margin_std_5y_pct_points"] = None
    result = score_payload({"target_id": "600001.SH", "metrics": metrics})
    assert result["raw_available_score"] == pytest.approx(100.0)
    assert result["coverage_ratio"] == pytest.approx(0.75)
    assert result["total_score"] == pytest.approx(92.5)


def test_point_in_time_index_snapshots_use_each_signal_dates_latest_visible_row(monkeypatch):
    def fake_cached_call(name, **kwargs):
        assert name == "get_index_weights"
        end = kwargs["end_date"]
        return pd.DataFrame([
            {"index_symbol": "000300.SH", "stock_symbol": "600001.SH", "date": end, "weight": 2.0},
            {"index_symbol": "000300.SH", "stock_symbol": "600002.SH", "date": end, "weight": 1.0},
        ])

    monkeypatch.setattr("scripts.dp_cache.cached_call", fake_cached_call)
    snapshots, source_dates = backtest_runner._point_in_time_index_snapshots(
        "000300.SH", ["20200102", "20210104"], 2
    )
    assert snapshots == {
        "20200102": ["600001.SH", "600002.SH"],
        "20210104": ["600001.SH", "600002.SH"],
    }
    assert source_dates == {"20200102": "20200102", "20210104": "20210104"}


def test_soft_portfolio_keeps_healthy_incumbents_and_caps_banks_and_industries():
    candidates = [
        {"target_id": "B1", "soft_eligible": True, "is_bank": True, "industry": "银行", "sell_triggers": []},
        {"target_id": "B2", "soft_eligible": True, "is_bank": True, "industry": "银行", "sell_triggers": []},
        {"target_id": "F1", "soft_eligible": True, "is_bank": False, "industry": "食品", "sell_triggers": []},
        {"target_id": "F2", "soft_eligible": True, "is_bank": False, "industry": "食品", "sell_triggers": []},
        {"target_id": "F3", "soft_eligible": True, "is_bank": False, "industry": "食品", "sell_triggers": []},
        {"target_id": "M1", "soft_eligible": True, "is_bank": False, "industry": "医药", "sell_triggers": []},
    ]
    picks = backtest_runner._select_soft_portfolio(candidates, ["F2"], hold_top=4)
    assert picks[0] == "F2"
    assert len(set(picks) & {"B1", "B2"}) == 1
    assert len(set(picks) & {"F1", "F2", "F3"}) == 2


def test_unknown_industries_do_not_form_a_fake_concentration_bucket():
    candidates = [
        {"target_id": f"U{i}", "soft_eligible": True, "is_bank": False, "industry": "", "sell_triggers": []}
        for i in range(4)
    ]
    assert backtest_runner._select_soft_portfolio(candidates, [], hold_top=4) == ["U0", "U1", "U2", "U3"]


def test_build_soft_ranking_promotes_only_review_shortlist():
    payloads = [
        {"target_id": "A", "quality_score": 10.0, "metrics": _metrics(), "sell_triggers": []},
        {"target_id": "B", "quality_score": 20.0, "metrics": {**_metrics(), "current_pe": 20.0}, "sell_triggers": []},
    ]
    ranked = build._apply_soft_financial_ranking(payloads, review_top=1)
    assert ranked[0]["target_id"] == "A"
    assert ranked[0]["decision"] == "research_candidate"
    assert ranked[0]["legacy_quality_score"] == 10.0
    assert ranked[1]["decision"] == "watchlist"
