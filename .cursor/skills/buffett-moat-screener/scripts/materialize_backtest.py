"""Materialize verified point-in-time backtest evidence into the BUILD schema."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))
    from scripts.core import BUILD_ID, BUILD_NAME, DATA_VERSION
    from scripts.panda_adapter import build_production_frame, write_production
else:
    from .core import BUILD_ID, BUILD_NAME, DATA_VERSION
    from .panda_adapter import build_production_frame, write_production


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run(input_data: Mapping[str, Any], config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(input_data, Mapping):
        raise TypeError("input_data must be a mapping")
    options = dict(config or {})
    soft_path = Path(input_data.get("soft_path") or ROOT / "生产产物" / "backtest_a_share_strict.json")
    hard_path = Path(input_data.get("hard_path") or ROOT / "output" / "hard_pit_2017_2026.json")
    roster_path = Path(input_data.get("roster_path") or ROOT / "生产产物" / "backtest_a_share_roster_2010.json")
    us_path = Path(input_data.get("us_path") or ROOT / "生产产物" / "backtest_us_fixed_roster.json")
    output_path = Path(options.get("output_path") or ROOT / "生产产物" / "数据库.parquet")
    soft = _load(soft_path).get("a_share", {})
    hard = _load(hard_path).get("a_share", {})
    roster = _load(roster_path).get("a_share", {})
    us = _load(us_path).get("us", {})
    required = {"start", "end", "performance", "benchmark_performance", "holdings_log"}
    if not required.issubset(soft) or not required.issubset(hard):
        raise ValueError("backtest JSON is missing required A-share fields")
    if soft.get("index_membership_mode") != "point_in_time" or hard.get("index_membership_mode") != "point_in_time":
        raise ValueError("production validation requires point-in-time index membership")
    if roster.get("mode") != "roster" or not roster.get("holdings_log"):
        raise ValueError("A-share fixed-roster diagnostic is missing")
    if us.get("universe_definition") != "fixed_research_roster_not_historical_sp500_or_berkshire_holdings":
        raise ValueError("US fixed-roster claim boundary is missing")

    final_log = soft["holdings_log"][-1]
    trade_date = str(soft["end"])
    source_signal_date = str(final_log["date"])
    comparison = {
        "evidence_scope": "quantitative_retrospective_diagnostic",
        "qualitative_gate_backtested": False,
        "audit_gate_backtested": False,
        "index_symbol": "000300.SH",
        "index_membership_mode": "point_in_time",
        "verified_start": str(soft["start"]),
        "verified_end": str(soft["end"]),
        "score_version": "soft-five-dimension-v1",
        "financial_threshold_mode": "soft_anchors",
        "bank_gross_margin": "N/A",
        "transaction_cost_bps": float(soft.get("transaction_cost_bps", 15.0)),
        "soft": soft["performance"],
        "legacy_hard": hard["performance"],
        "benchmark_000300": soft["benchmark_performance"],
        "soft_avg_names": sum(len(row.get("picks", [])) for row in soft["holdings_log"]) / len(soft["holdings_log"]),
        "hard_avg_names": sum(len(row.get("picks", [])) for row in hard["holdings_log"]) / len(hard["holdings_log"]),
        "interpretation": "soft beats CSI300 over the full sample but slightly trails it in the 2022-2026 diagnostic period and trails the concentrated legacy hard portfolio",
        "claim_boundary": "no universal return improvement and no future performance guarantee",
    }
    summary_path = soft_path.parent / "backtest_summary.json"
    if summary_path.exists():
        comparison["periods"] = _load(summary_path).get("periods", [])
    records: list[dict[str, Any]] = [
        {
            "trade_date": trade_date,
            "target_id": "Q44-BUFFETT-A-SHARE-V9-VALIDATION",
            "result_type": "strategy_validation",
            "result_value": "supported_vs_benchmark_mixed_vs_legacy_hard",
            "source_data_date": trade_date,
            "actual_source_date": trade_date,
            "coverage_status": "quantitative_only",
            "payload": comparison,
        },
        {
            "trade_date": trade_date,
            "target_id": "000300.SH",
            "result_type": "universe_summary",
            "result_value": "300",
            "source_data_date": source_signal_date,
            "actual_source_date": str(final_log.get("index_source_date") or source_signal_date),
            "coverage_status": "complete_from_20170103",
            "payload": {
                "index_symbol": "000300.SH",
                "point_in_time_count": int(final_log["point_in_time_universe_size"]),
                "historical_union_count": 595,
                "verified_start": str(soft["start"]),
                "verified_end": str(soft["end"]),
                "pre_2017_status": "unavailable_from_panda_data",
            },
        },
        {
            "trade_date": trade_date,
            "target_id": "CASH.CNY",
            "result_type": "portfolio_target_weight",
            "result_value": "1.0000000000",
            "source_data_date": trade_date,
            "actual_source_date": trade_date,
            "coverage_status": "complete",
            "payload": {"target_id": "CASH.CNY", "target_weight": 1.0, "reason": "research-only materialization preserves cash"},
        },
        {
            "trade_date": trade_date,
            "target_id": "Q44-BUFFETT-A-SHARE-V9",
            "result_type": "portfolio_summary",
            "result_value": "1.0000000000",
            "source_data_date": trade_date,
            "actual_source_date": trade_date,
            "coverage_status": "quantitative_only",
            "payload": {"holdings": [], "cash_weight": 1.0, "state": "research_only", "reason": "quantitative research materialization preserves cash"},
        },
        {
            "trade_date": trade_date,
            "target_id": "Q44-BUFFETT-A-SHARE-V9",
            "result_type": "qualitative_review",
            "result_value": "not_reviewed",
            "source_data_date": source_signal_date,
            "actual_source_date": source_signal_date,
            "coverage_status": "qualitative_pending",
            "payload": {"qualitative_verdict": "not_reviewed", "approved_count": 0, "candidate_scope": "quantitative_watchlist"},
        },
        {
            "trade_date": trade_date,
            "target_id": "Q44-BUFFETT-A-SHARE-V9",
            "result_type": "portfolio_state_transition",
            "result_value": "no_transition",
            "source_data_date": trade_date,
            "actual_source_date": trade_date,
            "coverage_status": "complete",
            "payload": {"review_action": "no_transition", "reason": "research-only materialization preserves cash"},
        },
        {
            "trade_date": trade_date,
            "target_id": "Q44-BUFFETT-A-ROSTER-V9-VALIDATION",
            "result_type": "strategy_validation",
            "result_value": "survivorship_biased_fixed_roster_diagnostic",
            "source_data_date": str(roster["end"]),
            "actual_source_date": str(roster["end"]),
            "coverage_status": "fixed_roster_survivorship_bias",
            "payload": {
                "verified_start": str(roster["start"]),
                "verified_end": str(roster["end"]),
                "universe_size": int(roster["universe_size"]),
                "performance": roster["performance"],
                "benchmark_000300": roster["benchmark_performance"],
                "transaction_cost_bps": 15.0,
                "claim_boundary": "fixed current research roster; not historical CSI300 selection and subject to survivorship bias",
            },
        },
        {
            "trade_date": trade_date,
            "target_id": "Q44-BUFFETT-US-ROSTER-V9-VALIDATION",
            "result_type": "strategy_validation",
            "result_value": "fixed_roster_price_return_diagnostic",
            "source_data_date": str(us["end"]),
            "actual_source_date": str(us["end"]),
            "coverage_status": "fixed_roster_no_benchmark",
            "payload": {
                "verified_start": str(us["start"]),
                "verified_end": str(us["end"]),
                "universe_size": int(us["universe_size"]),
                "performance": us["performance"],
                "benchmark_status": us.get("benchmark_status"),
                "return_definition": us["return_definition"],
                "score_version": us["score_version"],
                "split_events": us.get("split_events", []),
                "claim_boundary": "fixed research roster; not historical S&P 500 or Berkshire holdings; cash dividends excluded",
            },
        },
    ]
    details = {row["symbol"]: row for row in final_log.get("entry_details", [])}
    for symbol in final_log.get("picks", []):
        evidence = details.get(symbol, {})
        records.append(
            {
                "trade_date": source_signal_date,
                "target_id": symbol,
                "result_type": "buffett_research_candidate",
                "result_value": "quantitative_watchlist",
                "source_data_date": source_signal_date,
                "actual_source_date": source_signal_date,
                "coverage_status": "quantitative_only",
                "payload": {
                    **evidence,
                    "decision": "quantitative_watchlist",
                    "qualitative_verdict": "not_reviewed",
                    "entry_eligible": False,
                    "score_version": "soft-five-dimension-v1",
                    "bank_gross_margin_policy": "N/A and weight redistributed" if evidence.get("special_case") == "bank_roa" else "applicable",
                },
            }
        )
    frame = build_production_frame(
        build_id=BUILD_ID,
        build_name=BUILD_NAME,
        trade_date=trade_date,
        records=records,
        data_version=DATA_VERSION,
        run_id=f"{BUILD_ID}-soft-pit-{trade_date}",
    )
    write_production(frame, output_path, upsert=False, replace_all=True)
    return {"output_path": str(output_path), "rows": len(frame), "data_version": DATA_VERSION}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--soft", default=str(ROOT / "生产产物" / "backtest_a_share_strict.json"))
    parser.add_argument("--hard", default=str(ROOT / "output" / "hard_pit_2017_2026.json"))
    parser.add_argument("--roster", default=str(ROOT / "生产产物" / "backtest_a_share_roster_2010.json"))
    parser.add_argument("--us", default=str(ROOT / "生产产物" / "backtest_us_fixed_roster.json"))
    parser.add_argument("--output", default=str(ROOT / "生产产物" / "数据库.parquet"))
    args = parser.parse_args()
    result = run(
        {"soft_path": args.soft, "hard_path": args.hard, "roster_path": args.roster, "us_path": args.us},
        {"output_path": args.output},
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
