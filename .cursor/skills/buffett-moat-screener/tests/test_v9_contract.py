import json

import pandas as pd
import pytest
import scripts.build as build
import scripts.data_pipeline as data_pipeline
import scripts.demo as demo
from scripts.v9_backtest import _equity_only_signals, _history_ready_snapshots, rules_fingerprint, stratified_sample_symbols

from scripts.core import AUTO_PATTERN, CYCLICAL_PATTERN, DATA_VERSION
from scripts.feasibility import run_feasibility
from scripts.portfolio import _candidate_key, build_portfolio
from scripts.reporting import _html_report
from scripts.render_soft_report import _rebalance_history
from scripts.panda_adapter import PandaDataError, _call_with_timeout
from scripts.scoring import evaluate_buffett_company
from scripts.validation import validate_input
from scripts.validation import validate_production
from scripts.v9_engine import conviction_score, next_open_date, opportunity_replacement, quantitative_proxy_score, quarterly_safety_status, quarterly_ttm, resolve_all_a, transition_holding, valuation_score


def test_v9_rebalance_report_explains_hold_buy_sell_and_reasons():
    report = _rebalance_history([{
        "date": "20240102",
        "picks": ["600001.SH", "000001.SZ"],
        "new_entries": ["000001.SZ"],
        "kept": ["600001.SH"],
        "removed": ["300001.SZ"],
        "turnover": 0.5,
        "transaction_cost_bps": 15,
        "reason_summary": "新入 1、保留 1、剔除 1。",
        "entry_details": [
            {"symbol": "600001.SH", "name": "继续持有公司"},
            {"symbol": "000001.SZ", "name": "新公司"},
        ],
        "removed_reasons": [{
            "symbol": "300001.SZ",
            "name": "退出<公司>",
            "sell_triggers": ["normalized_profit_nonpositive"],
        }],
    }])

    assert "调仓后持仓" in report
    assert "新买入" in report and "继续持有" in report and "卖出" in report
    assert "正常化利润转负" in report
    assert "退出&lt;公司&gt;" in report
    assert "换手率 50.0%" in report and "15bp" in report


def test_v9_all_a_is_point_in_time_and_excludes_bj():
    details = pd.DataFrame([
        {"symbol": "600001.SH", "listed_date": "20100101", "de_listed_date": None},
        {"symbol": "000001.SZ", "listed_date": "20150101", "de_listed_date": "20220101"},
        {"symbol": "430001.BJ", "listed_date": "20100101", "de_listed_date": None},
        {"symbol": "600002.SH", "listed_date": "20250101", "de_listed_date": None},
    ])
    assert resolve_all_a(details, "20201231")["symbol"].tolist() == ["600001.SH", "000001.SZ"]
    assert resolve_all_a(details, "20260101")["symbol"].tolist() == ["600001.SH", "600002.SH"]


def test_v9_cyclical_route_uses_sector_as_a_review_signal():
    assert AUTO_PATTERN.search("汽车")
    assert CYCLICAL_PATTERN.search("化工")
    assert CYCLICAL_PATTERN.search("建筑材料")


def test_v9_diagnostic_sampling_is_not_code_prefix_sampling():
    symbols = ["000001.SZ", "000002.SZ", "600001.SH", "600002.SH", "300001.SZ", "688001.SH"]
    details = pd.DataFrame([
        {"symbol": "000001.SZ", "listed_date": "20100101", "board_type": "main"},
        {"symbol": "000002.SZ", "listed_date": "20200101", "board_type": "main"},
        {"symbol": "600001.SH", "listed_date": "20150101", "board_type": "main"},
        {"symbol": "600002.SH", "listed_date": "20220101", "board_type": "main"},
        {"symbol": "300001.SZ", "listed_date": "20150101", "board_type": "gem"},
        {"symbol": "688001.SH", "listed_date": "20200101", "board_type": "star"},
    ])
    sample = stratified_sample_symbols(symbols, details, 4)
    assert len(sample) == 4
    assert len({symbol.rsplit(".", 1)[-1] for symbol in sample}) == 2
    assert sample != sorted(symbols)[:4]


def test_v9_mature_diagnostic_sampling_excludes_recent_listings():
    symbols = ["000001.SZ", "000002.SZ", "600001.SH", "600002.SH"]
    details = pd.DataFrame([
        {"symbol": "000001.SZ", "listed_date": "20000101", "board_type": "main"},
        {"symbol": "000002.SZ", "listed_date": "20200101", "board_type": "main"},
        {"symbol": "600001.SH", "listed_date": "20050101", "board_type": "main"},
        {"symbol": "600002.SH", "listed_date": "20220101", "board_type": "main"},
    ])
    sample = stratified_sample_symbols(symbols, details, 4, as_of="20260717", mature_only=True)
    assert set(sample) == {"000001.SZ", "600001.SH"}


def test_v9_auto_start_requires_complete_years_not_only_filing_rows():
    rows = []
    for year in range(2010, 2019):
        rows.append({
            "symbol": "600001.SH", "quarter": f"{year}q4", "date": f"{year + 1}0430",
            "is_n_income_attr_p": 10, "bs_total_hldr_eqy_exc_min_int": 100,
            "is_basic_eps": 1, "cfs_net_cash_operating": 12, "is_revenue": 50,
        })
    snapshots = [{"signal_date": "20190430", "execution_date": "20190506"}]
    assert _history_ready_snapshots(snapshots, pd.DataFrame(rows), minimum_years=8) == snapshots
    assert _history_ready_snapshots(snapshots, pd.DataFrame(rows[:-1]), minimum_years=8) == []


def test_v9_ttm_uses_current_ytd_plus_prior_q4_minus_prior_ytd():
    frame = pd.DataFrame([
        {"symbol": "600001.SH", "quarter": "2024q2", "date": "20240830", "parent_net_profit": 60, "basic_eps": 0.6},
        {"symbol": "600001.SH", "quarter": "2023q2", "date": "20230830", "parent_net_profit": 40, "basic_eps": 0.4},
        {"symbol": "600001.SH", "quarter": "2023q4", "date": "20240430", "parent_net_profit": 90, "basic_eps": 0.9},
    ])
    result = quarterly_ttm(frame, symbol="600001.SH")
    assert result["ttm"]["parent_net_profit"] == 110
    assert result["ttm"]["basic_eps"] == 1.1
    assert result["event_date"] == "20240830"
    assert result["as_of_revision"] == "20240830"


def test_v9_quarterly_safety_blocks_nonpositive_ttm():
    frame = pd.DataFrame([
        {"symbol": "600001.SH", "quarter": "2024q2", "date": "20240830", "parent_net_profit": -5, "basic_eps": -0.1},
        {"symbol": "600001.SH", "quarter": "2023q2", "date": "20230830", "parent_net_profit": 10, "basic_eps": 0.2},
        {"symbol": "600001.SH", "quarter": "2023q4", "date": "20240430", "parent_net_profit": 8, "basic_eps": 0.3},
    ])
    result = quarterly_safety_status(frame, symbol="600001.SH", as_of="20240901")
    assert result["status"] == "warning"


def test_v9_stale_quarterly_evidence_freezes_new_entry_without_exit():
    frame = pd.DataFrame([
        {"symbol": "600001.SH", "quarter": "2024q2", "date": "20240830", "parent_net_profit": 60, "basic_eps": 0.6},
        {"symbol": "600001.SH", "quarter": "2023q2", "date": "20230830", "parent_net_profit": 40, "basic_eps": 0.4},
        {"symbol": "600001.SH", "quarter": "2023q4", "date": "20240430", "parent_net_profit": 90, "basic_eps": 0.9},
    ])
    result = quarterly_safety_status(frame, symbol="600001.SH", as_of="20260201", max_age_days=180)
    assert result["status"] == "stale"
    assert result["stale_days"] > 180


def test_v9_equity_only_counterfactual_normalizes_stock_weights():
    signals = _equity_only_signals([{
        "signal_date": "20260719",
        "execution_date": "20260720",
        "target_weights": {"600001.SH": 0.25, "600002.SZ": 0.15, "CASH.CNY": 0.60},
        "actions": [{"target_id": "600001.SH", "review_action": "enter"}],
    }])
    assert signals[0]["actions"] == []
    assert signals[0]["target_weights"] == {"600001.SH": pytest.approx(0.625), "600002.SZ": pytest.approx(0.375)}


def test_v9_pending_qualitative_review_does_not_accumulate_sell_warning():
    previous = {
        "target_id": "600001.SH",
        "annual_warning_count": 1,
        "policy_weight": 0.10,
    }
    updated, transition = transition_holding(
        previous,
        {"qualitative_verdict": "qualitative_pending"},
        event_date="20260720",
    )
    assert updated is not None
    assert updated["annual_warning_count"] == 1
    assert transition.action == "warning_hold"


def test_v9_insufficient_data_preserves_existing_holding_without_warning_accumulation():
    previous = {"target_id": "600001.SH", "annual_warning_count": 1, "policy_weight": 0.10}
    updated, transition = transition_holding(
        previous,
        {"decision": "insufficient_data", "hold_status": "warning"},
        event_date="20260720",
    )
    assert updated is not None
    assert updated["annual_warning_count"] == 1
    assert transition.reason == "evidence_insufficient_no_forced_exit"


def test_v9_duplicate_warning_event_is_idempotent():
    previous = {"target_id": "600001.SH", "annual_warning_count": 1, "last_warning_event": "20260720"}
    updated, transition = transition_holding(
        previous,
        {"hold_status": "warning", "event_revision_date": "20260720"},
        event_date="20260721",
    )
    assert updated is not None
    assert updated["annual_warning_count"] == 1
    assert transition.reason == "duplicate_warning_event_no_new_count"


def test_v9_state_transition_unions_quantitative_and_qualitative_exit_flags():
    previous = {"target_id": "600001.SH", "policy_weight": 0.10}
    updated, transition = transition_holding(
        previous,
        {"sell_triggers": ["debt_to_profit_at_least_6"], "serious_flags": ["related_party_red_flag"]},
        event_date="20260720",
    )
    assert updated is None
    assert transition.action == "exit"
    assert set(transition.reason.split(",")) == {"debt_to_profit_at_least_6", "related_party_red_flag"}


def test_v9_conviction_and_valuation_are_quality_first():
    assert valuation_score(cash_yield=0.03) == 60
    assert conviction_score(95, 80, 60) == 83.75
    assert quantitative_proxy_score(95, 60) == 95.0


def test_v9_portfolio_ranking_uses_conviction_before_price_or_quality_tiebreaks():
    stronger_thesis = {
        "target_id": "600001.SH",
        "conviction_score": 88,
        "quality_score": 80,
        "valuation_score": 60,
        "cash_earnings_yield_proxy": 0.03,
    }
    cheaper_but_weaker_thesis = {
        "target_id": "600002.SH",
        "conviction_score": 86,
        "quality_score": 95,
        "valuation_score": 100,
        "cash_earnings_yield_proxy": 0.08,
    }
    assert sorted([stronger_thesis, cheaper_but_weaker_thesis], key=_candidate_key)[0]["target_id"] == "600001.SH"


def test_v9_materialized_holdings_use_the_same_conviction_order_as_selection():
    rows = []
    for symbol, conviction, quality in (("600001.SH", 78, 95), ("600002.SH", 88, 80)):
        rows.append({
            "target_id": symbol,
            "decision": "research_candidate",
            "entry_eligible": True,
            "quality_score": quality,
            "qualitative_score": 80,
            "qualitative_confidence": 90,
            "qualitative_verdict": "approve",
            "valuation_score": 80,
            "conviction_score": conviction,
            "cash_earnings_yield_proxy": 0.04,
            "sell_triggers": [],
            "hold_status": "healthy",
            "industry": "",
            "special_case": None,
        })
    result = build_portfolio(rows, signal_date="20260719", execution_date="20260720")
    assert [row["target_id"] for row in result["holdings"]] == ["600002.SH", "600001.SH"]


def test_v9_quantitative_replay_marks_audit_gate_as_not_backtested():
    history = pd.DataFrame(
        [{"symbol": "600001.SH", "year": year, "parent_net_profit": 1.0, "basic_eps": 1.0}
         for year in range(2014, 2025)]
    )
    result = evaluate_buffett_company(
        "600001.SH", history, industry="", audit_history=[], as_of_year=2024,
        audit_gate=False,
    )
    assert result["audit_status"] == "not_backtested"
    assert result["audit_freshness"] == "not_backtested"


def test_v9_quantitative_candidate_enters_without_external_review():
    base = {
        "target_id": "600001.SH", "decision": "research_candidate", "entry_eligible": True,
        "quality_score": 90, "valuation_score": 80, "conviction_score": 87,
        "cash_earnings_yield_proxy": 0.04, "industry": "食品饮料", "special_case": None,
        "sell_triggers": [], "hold_status": "healthy",
    }
    result = build_portfolio([base], signal_date="20260719", execution_date="20260720", qualitative_required=False)
    assert result["holdings"][0]["holding_since"] == "20260720"


def test_v9_no_minimum_holding_period_and_t1_feasibility():
    validate_input({"as_of_date": "20260719", "universe": "all_a"})
    calendar = pd.DataFrame({"date": ["20260719", "20260720", "20260721"], "is_open": [1, 1, 1]})
    assert next_open_date(calendar, "20260719") == "20260720"
    prices = pd.DataFrame([
        {"date": "20260720", "symbol": "600001.SH", "open": 10, "close": 10},
        {"date": "20260721", "symbol": "600001.SH", "open": 10, "close": 11},
    ])
    result = run_feasibility({"as_of_date": "20260721", "events": [{"event_date": "20260719", "target_weights": {"600001.SH": 1.0}}], "prices": prices, "benchmark": pd.DataFrame({"date": ["20260720", "20260721"], "close": [10, 10]})})
    assert DATA_VERSION == "9.4.0"
    assert result["qualitative_gate_backtested"] is False
    assert result["rebalance"][0]["execution_date"] == "20260720"
    assert result["nav"][-1]["strategy_nav"] > 1


def test_v9_report_separates_actual_and_policy_weights():
    result = {
        "data_version": DATA_VERSION,
        "as_of_date": "20260720",
        "periods": {"full": {"strategy": {"cagr": 0.1, "max_drawdown": -0.1}, "benchmark_000985": {"cagr": 0.08}}},
        "current_actual_cash_weight": 0.158,
        "current_cash_weight": 0.0,
        "current_actual_holdings": [{
            "target_id": "600001.SH", "industry": "消费", "actual_weight": 0.842,
            "policy_weight": 0.8, "quality_score": 80, "holding_since": "20200101",
            "evidence": {"metrics": {"owner_earnings_positive_year_ratio": 1}}, "review_action": "hold",
        }],
        "attribution": {}, "attribution_scope": {}, "coverage_summary": {},
        "qualitative_gate_backtested": False, "disclaimer": "仅供研究",
    }
    report = _html_report(result, pd.DataFrame({"date": ["20200101", "20200102"], "strategy_nav": [1, 1.1], "benchmark_000985_nav": [1, 1.05]}))
    assert "实际权重" in report and "政策目标" in report
    assert "15.8%" in report
    assert "政策权重</th>" not in report


def test_v9_healthy_existing_holding_can_reinvest_when_valuation_blocks_new_entry():
    prior_holding = {
        "target_id": "600001.SH",
        "holding_since": "20220505",
        "annual_warning_count": 0,
        "policy_weight": 0.20,
        "actual_weight": 0.20,
        "policy_ceiling": 0.25,
        "industry": "食品饮料",
        "special_case": None,
    }
    record = {
        "target_id": "600001.SH",
        "decision": "watchlist",
        "quality_score": 88.0,
        "entry_eligible": False,
        "hold_status": "healthy",
        "sell_triggers": [],
        "serious_flags": [],
        "conviction_score": None,
        "qualitative_verdict": "not_backtested",
        "qualitative_confidence": None,
        "industry": "食品饮料",
        "special_case": None,
    }
    result = build_portfolio(
        [record],
        signal_date="20260719",
        execution_date="20260720",
        prior_state={"holdings": [prior_holding]},
        qualitative_required=False,
    )
    assert result["holdings"][0]["policy_weight"] == pytest.approx(0.25)
    assert result["transitions"][-1]["reason"] == "existing_quality_thesis_reinvestment_below_policy_ceiling"


def test_v9_backtest_checkpoint_changes_when_rules_change():
    base = {"quality_score_min": 70.0, "bank_roa_floor_min": 0.6}
    changed = {**base, "bank_roa_floor_min": 0.7}
    assert rules_fingerprint(base) != rules_fingerprint(changed)
    assert rules_fingerprint(base).startswith(f"{DATA_VERSION}:")


def test_v9_panda_request_timeout_is_bounded(monkeypatch):
    import time

    monkeypatch.setenv("PANDA_DATA_REQUEST_TIMEOUT", "1")

    def slow(**kwargs):
        time.sleep(2)

    with __import__("pytest").raises(PandaDataError, match="timed out"):
        _call_with_timeout(slow, {}, "test_endpoint")


def test_v9_data_pipeline_cache_is_request_scoped_and_reusable(monkeypatch, tmp_path):
    calls = []

    def fake_fetch(name, **kwargs):
        calls.append((name, kwargs))
        return pd.DataFrame([{"symbol": "600001.SH", "date": "20260719", "close": 10.0}])

    monkeypatch.setattr(data_pipeline, "_panda_fetch", fake_fetch)
    data_pipeline.configure_cache(tmp_path)
    try:
        first = data_pipeline.fetch("get_stock_daily", symbol=["600001.SH"], start_date="20260719", end_date="20260719")
        second = data_pipeline.fetch("get_stock_daily", symbol=["600001.SH"], start_date="20260719", end_date="20260719")
    finally:
        data_pipeline.configure_cache(None)
    assert len(calls) == 1
    pd.testing.assert_frame_equal(first, second)
    assert list(tmp_path.glob("*.parquet"))


def test_v9_backtest_price_loader_deduplicates_symbol_date(monkeypatch):
    def fake_fetch(name, **kwargs):
        if name == "get_stock_daily_post":
            return pd.DataFrame([
                {"symbol": "600001.SH", "date": "20200102", "open": 10.0, "close": 10.5, "volume": 100},
                {"symbol": "600001.SH", "date": "20200102", "open": 10.0, "close": 10.5, "volume": 100},
            ])
        if name == "get_stock_daily":
            return pd.DataFrame([
                {"symbol": "600001.SH", "date": "20200102", "open": 10.0, "pre_close": 9.8, "volume": 100, "limit_up": False, "limit_down": False},
                {"symbol": "600001.SH", "date": "20200102", "open": 10.0, "pre_close": 9.8, "volume": 100, "limit_up": False, "limit_down": False},
            ])
        raise AssertionError(name)

    monkeypatch.setattr(data_pipeline, "fetch", fake_fetch)
    result = data_pipeline.fetch_stock_backtest_prices(["600001.SH"], "20200101", "20200103", batch_size=1)
    assert len(result) == 1
    assert not result.duplicated(["symbol", "date"]).any()


def test_v9_backtest_price_loader_resumes_completed_batches(monkeypatch, tmp_path):
    calls = []

    def fake_fetch(name, **kwargs):
        calls.append(name)
        if name == "get_stock_daily_post":
            return pd.DataFrame([{"symbol": "600001.SH", "date": "20200102", "open": 10.0, "close": 10.5, "volume": 100}])
        return pd.DataFrame([{"symbol": "600001.SH", "date": "20200102", "open": 10.0, "pre_close": 9.8, "volume": 100, "limit_up": False, "limit_down": False}])

    monkeypatch.setattr(data_pipeline, "fetch", fake_fetch)
    first = data_pipeline.fetch_stock_backtest_prices(["600001.SH"], "20200101", "20200103", batch_size=1, cache_dir=tmp_path)
    first_call_count = len(calls)

    def fail_fetch(*args, **kwargs):
        raise AssertionError("completed price batch was fetched again")

    monkeypatch.setattr(data_pipeline, "fetch", fail_fetch)
    second = data_pipeline.fetch_stock_backtest_prices(["600001.SH"], "20200101", "20200103", batch_size=1, cache_dir=tmp_path)
    assert first_call_count == 2
    pd.testing.assert_frame_equal(first, second)


def test_v9_signal_price_loader_fetches_short_windows_and_deduplicates(monkeypatch):
    calls = []

    def fake_fetch(name, **kwargs):
        calls.append(kwargs)
        return pd.DataFrame([
            {"symbol": "600001.SH", "date": "20260719", "close": 10.0},
            {"symbol": "600001.SH", "date": "20260719", "close": 10.0},
        ])

    monkeypatch.setattr(data_pipeline, "fetch", fake_fetch)
    result = data_pipeline.fetch_signal_price_frames(
        ["600001.SH"], ["20260719"], batch_size=1
    )
    assert len(calls) == 1
    assert calls[0]["start_date"] == "20260619"
    assert len(result["20260719"]) == 1


def test_v9_signal_price_loader_keeps_other_windows_after_one_request_failure(monkeypatch):
    calls = []

    def fake_fetch(name, **kwargs):
        calls.append(kwargs["end_date"])
        if kwargs["end_date"] == "20260719":
            raise data_pipeline.PandaDataError("timeout")
        return pd.DataFrame([{"symbol": "600001.SH", "date": "20260718", "close": 10.0}])

    monkeypatch.setattr(data_pipeline, "fetch", fake_fetch)
    result, failures = data_pipeline.fetch_signal_price_frames(
        ["600001.SH"], ["20260718", "20260719"], batch_size=1, return_failures=True
    )
    assert "20260719" in {row["signal_date"] for row in failures}
    assert len(result["20260718"]) == 1


def test_v9_index_and_cash_partition_loaders_deduplicate_dates(monkeypatch):
    def fake_fetch(name, **kwargs):
        return pd.DataFrame([
            {"symbol": kwargs.get("symbol", ["000985.SH"])[0], "date": "20200102", "close": 10.0},
            {"symbol": kwargs.get("symbol", ["000985.SH"])[0], "date": "20200102", "close": 10.0},
        ])

    monkeypatch.setattr(data_pipeline, "fetch", fake_fetch)
    index = data_pipeline.fetch_index_prices("000985.SH", "20190101", "20210101")
    cash = data_pipeline.fetch_fund_post("511880.SH", "20190101", "20210101")
    assert len(index) == 1 and not index.duplicated(["symbol", "date"]).any()
    assert len(cash) == 1 and not cash.duplicated(["symbol", "date"]).any()


def test_v9_build_emits_quantitative_queue_and_portfolio(monkeypatch, tmp_path):
    monkeypatch.setattr(build.data_pipeline, "discover_all_a", lambda as_of: (["600001.SH"], pd.DataFrame()))
    monkeypatch.setattr(build, "sdk_version", lambda: "0.0.12")
    monkeypatch.setattr(build, "screen_symbols", lambda symbols, as_of, **kwargs: ([{
        "target_id": "600001.SH", "decision": "research_candidate", "quality_score": 88,
        "entry_eligible": True, "cash_earnings_yield_proxy": 0.04, "normalized_pe": 20,
        "metrics": {"pb": 1.2}, "industry": "食品饮料", "special_case": None,
        "sell_triggers": [], "hold_status": "healthy", "actual_source_date": as_of,
    }], pd.DataFrame()))
    result = build.run({"as_of_date": "20260719", "universe": "all_a"}, {"output_path": str(tmp_path / "db.parquet")})
    assert result["data_version"] == "9.4.0"
    assert 0.0 <= result["portfolio"]["cash_weight"] <= 1.0
    assert {row["result_type"] for row in result["records"]} == {"buffett_research_candidate"}
    guidance = result["buffett_guidance"]
    assert guidance["method"] == "buffett_style_quantitative_research_guidance"
    assert guidance["research_actions"]
    assert "不构成买卖指令" in guidance["boundary"]


def test_demo_reuses_production_snapshot_offline_and_renders_html(tmp_path):
    candidate = {
        "target_id": "600519.SH",
        "decision": "quantitative_research_candidate",
        "entry_eligible": True,
        "soft_score": 88.0,
        "valuation_score": 70.0,
        "industry": "食品饮料",
        "score_coverage": 1.0,
    }
    portfolio = {"state": "research_only", "cash_weight": 1.0, "holdings": [], "reason": "demo"}
    frame = pd.DataFrame([
        {"trade_date": "20260724", "target_id": "600519.SH", "result_type": "buffett_research_candidate", "result_json": json.dumps(candidate), "data_version": DATA_VERSION, "update_time": "2026-07-24T00:00:00Z"},
        {"trade_date": "20260724", "target_id": "Q44", "result_type": "portfolio_summary", "result_json": json.dumps(portfolio), "data_version": DATA_VERSION, "update_time": "2026-07-24T00:00:00Z"},
    ])
    path = tmp_path / "production.parquet"
    frame.to_parquet(path, index=False)

    result = demo.run_demo(path)
    report = demo._html_report(result)

    assert result["mode"] == "production_snapshot"
    assert result["source"]["network_called"] is False
    assert result["buffett_guidance"]["research_actions"]
    assert "不构成买卖指令" in result["buffett_guidance"]["boundary"]
    assert "巴菲特式研究建议" in report


def test_demo_annual_holdings_preserve_scope_and_rebalance_evidence(tmp_path):
    backtest = {
        "a_share": {
            "holdings_log": [{
                "date": "20200102",
                "picks": ["600519.SH"],
                "entry_details": [{"symbol": "600519.SH", "name": "贵州茅台", "industry": "食品饮料", "reason": "品牌护城河"}],
                "new_entries": ["600519.SH"],
                "kept": [],
                "removed": [],
                "turnover": 1.0,
                "transaction_cost_bps": 15.0,
                "reason_summary": "新入 1、保留 0、剔除 0。",
            }]
        }
    }
    path = tmp_path / "annual.json"
    path.write_text(json.dumps(backtest), encoding="utf-8")

    items = demo._annual_holding_items(path, scope="严格点时沪深 300", scope_note="点时口径")

    assert items[0]["year"] == "2020"
    assert items[0]["holdings"] == [{"symbol": "600519.SH", "name": "贵州茅台", "industry": "食品饮料", "reason": "品牌护城河"}]
    assert items[0]["new_entries"] == ["600519.SH"]


def test_v9_build_reuses_same_signal_materialized_portfolio(monkeypatch, tmp_path):
    monkeypatch.setattr(build.data_pipeline, "discover_all_a", lambda as_of: (["600001.SH"], pd.DataFrame()))
    monkeypatch.setattr(build, "sdk_version", lambda: "0.0.12")
    monkeypatch.setattr(build, "screen_symbols", lambda symbols, as_of, **kwargs: ([{
        "target_id": "600001.SH", "decision": "watchlist", "quality_score": 60,
        "entry_eligible": False, "cash_earnings_yield_proxy": 0.02, "normalized_pe": 40,
        "metrics": {"pb": 1.2}, "industry": "食品饮料", "special_case": None,
        "sell_triggers": [], "hold_status": "healthy", "actual_source_date": as_of,
    }], pd.DataFrame()))
    cached = {"strategy_id": "cached", "signal_date": "20260719", "execution_date": "20260720", "holdings": [], "cash_weight": 1.0, "transitions": [], "state_origin": "materialized_current_review"}
    monkeypatch.setattr(build, "load_materialized_portfolio", lambda *args, **kwargs: cached)
    result = build.run({"as_of_date": "20260719", "universe": "all_a"}, {"output_path": str(tmp_path / "db.parquet")})
    assert result["portfolio"]["strategy_id"] == "cached"
    assert result["portfolio"]["state_origin"] == "materialized_current_review"


def test_v9_reference_capital_blocks_capacity_insufficient_new_entries():
    payloads = [{"target_id": "600001.SH", "decision": "research_candidate", "entry_eligible": True}]
    liquidity = pd.DataFrame(
        [{"symbol": "600001.SH", "turnover": 1_000_000.0, "date": f"202607{day:02d}"} for day in range(1, 61)]
    )
    build._apply_capacity_gate(payloads, liquidity, capital=10_000_000, thresholds={})
    assert payloads[0]["liquidity_capacity"] == "liquidity_or_capacity_insufficient"
    assert payloads[0]["entry_eligible"] is False
    assert payloads[0]["decision"] == "watchlist"


def test_v9_market_status_gate_blocks_risky_entries_and_adds_exit_trigger():
    payloads = [{"target_id": "600001.SH", "decision": "research_candidate", "entry_eligible": True, "sell_triggers": []}]
    snapshot = pd.DataFrame([{"symbol": "600001.SH", "risk_flags": ["st_risk", "delisting_risk"]}])
    build._apply_market_status_gate(payloads, snapshot)
    assert payloads[0]["decision"] == "watchlist"
    assert payloads[0]["entry_eligible"] is False
    assert set(payloads[0]["sell_triggers"]) == {"st_risk", "delisting_risk"}


def test_v9_market_status_missing_freezes_new_entry_without_sell_trigger():
    payloads = [{"target_id": "600001.SH", "decision": "research_candidate", "entry_eligible": True, "sell_triggers": []}]
    build._apply_market_status_gate(payloads, pd.DataFrame())
    assert payloads[0]["decision"] == "watchlist"
    assert payloads[0]["risk_flags"] == ["market_status_unobserved"]
    assert payloads[0]["sell_triggers"] == []


def test_v9_soft_quality_score_warning_does_not_break_long_term_thesis():
    prior = {
        "holdings": [{
            "target_id": "600001.SH",
            "holding_since": "20220505",
            "annual_warning_count": 1,
            "policy_weight": 0.20,
            "actual_weight": 0.20,
            "industry": "食品饮料",
            "special_case": None,
        }]
    }
    evidence = {
        "target_id": "600001.SH",
        "decision": "watchlist",
        "quality_score": 64.0,
        "entry_eligible": False,
        "hold_status": "warning",
        "warning_reasons": ["quality_score_soft_warning"],
        "sell_triggers": [],
        "serious_flags": [],
        "industry": "食品饮料",
        "special_case": None,
    }
    result = build_portfolio(
        [evidence],
        signal_date="20260719",
        execution_date="20260720",
        prior_state=prior,
        qualitative_required=False,
    )
    assert result["holdings"] == []
    assert result["transitions"][0]["reason"] == "two_consecutive_quality_warnings"


def test_v9_quantitative_opportunity_replacement_uses_proxy_without_external_review():
    incumbent = {"quality_score": 80, "valuation_score": 60, "conviction_score": 80, "qualitative_score": None}
    newcomer = {"quality_score": 86, "valuation_score": 76, "conviction_score": 91, "qualitative_score": None}
    assert opportunity_replacement(incumbent, newcomer, quantitative=True)
    assert not opportunity_replacement(incumbent, newcomer, quantitative=False)


def test_v9_materialization_is_14_columns_and_versioned(monkeypatch, tmp_path):
    monkeypatch.setattr(build.data_pipeline, "discover_all_a", lambda as_of: (["600001.SH"], pd.DataFrame()))
    monkeypatch.setattr(build, "sdk_version", lambda: "0.0.12")
    monkeypatch.setattr(build, "screen_symbols", lambda symbols, as_of, **kwargs: ([{
        "target_id": "600001.SH", "decision": "watchlist", "quality_score": 60,
        "entry_eligible": False, "cash_earnings_yield_proxy": 0.02, "normalized_pe": 40,
        "metrics": {"pb": 1.2}, "industry": "食品饮料", "special_case": None,
        "sell_triggers": [], "hold_status": "warning", "actual_source_date": as_of,
    }], pd.DataFrame()))
    output_path = tmp_path / "database.parquet"
    build.run({"as_of_date": "20260719", "universe": "all_a"}, {"output_path": str(output_path), "materialize": True})
    result = validate_production(output_path)
    assert result["data_version"] == "9.4.0"
    assert result["schema_version"] == "3.0.0"
