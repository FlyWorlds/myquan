"""Q44 V9 public build entry point.

The build is a quantitative research queue and portfolio state update.  It
never emits orders.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import data_pipeline
    from scripts.analysis import RESEARCH_CHECKLIST
    from scripts.core import BUILD_ID, BUILD_NAME, BUFFETT_STRICT_THRESHOLDS, DATA_VERSION, DEFAULT_THRESHOLDS, SCHEMA_VERSION
    from scripts.panda_adapter import PandaDataError, build_production_frame, clear_process_credentials, sdk_version, write_versioned_production
    from scripts.portfolio import build_portfolio, load_materialized_portfolio, load_portfolio_state
    from scripts.scoring import rank_buffett_candidates
    from scripts.screener import screen_symbols
    from scripts.validation import validate_input
    from scripts.v9_engine import capacity_check, conviction_score, next_open_date, valuation_score
else:
    from . import data_pipeline
    from .analysis import RESEARCH_CHECKLIST
    from .core import BUILD_ID, BUILD_NAME, BUFFETT_STRICT_THRESHOLDS, DATA_VERSION, DEFAULT_THRESHOLDS, SCHEMA_VERSION
    from .panda_adapter import PandaDataError, build_production_frame, clear_process_credentials, sdk_version, write_versioned_production
    from .portfolio import build_portfolio, load_materialized_portfolio, load_portfolio_state
    from .scoring import rank_buffett_candidates
    from .screener import screen_symbols
    from .validation import validate_input
    from .v9_engine import capacity_check, conviction_score, next_open_date, valuation_score


ALLOWED_CONFIG = {"thresholds", "preset", "materialize", "output_path", "batch_size", "reference_capital", "capital", "portfolio_state"}
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "生产产物" / "数据库.parquet"
DEFAULT_CACHE = Path(__file__).resolve().parents[1] / "output" / "panda_cache"


def _validate_config(config: Mapping[str, Any]) -> None:
    unknown = sorted(set(config) - ALLOWED_CONFIG)
    if unknown:
        raise ValueError(f"不支持的 config 字段：{unknown}")
    if "batch_size" in config and (not isinstance(config["batch_size"], int) or config["batch_size"] <= 0):
        raise ValueError("batch_size 必须是正整数")
    if "reference_capital" in config and (not isinstance(config["reference_capital"], (int, float)) or config["reference_capital"] <= 0):
        raise ValueError("reference_capital 必须为正数")
    if "capital" in config and (not isinstance(config["capital"], (int, float)) or config["capital"] <= 0):
        raise ValueError("capital 必须为正数")
    if "portfolio_state" in config and not isinstance(config["portfolio_state"], Mapping):
        raise ValueError("portfolio_state 必须是映射")
def _records(payloads: list[dict[str, Any]], as_of: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for payload in payloads:
        payload.update({
            "universe_status": payload.get("universe_status", "point_in_time_valid"),
            "event_date": str(payload.get("event_date") or as_of),
            "event_type": payload.get("event_type", "daily_price"),
            "quarterly_safety_status": payload.get("quarterly_safety_status", "not_recomputed"),
            "liquidity_capacity": payload.get("liquidity_capacity", "not_observed"),
            "qualitative_score": None,
            "qualitative_verdict": "not_requested",
            "qualitative_confidence": None,
            "valuation_score": valuation_score(
                cash_yield=payload.get("cash_earnings_yield_proxy"),
                normalized_pe=payload.get("normalized_pe"),
                pb=(payload.get("metrics") or {}).get("pb"),
                bank=payload.get("special_case") == "bank_roa",
            ),
        })
        payload["conviction_score"] = None
        records.append({
            **payload,
            "result_type": "buffett_research_candidate",
            "result_value": str(payload["decision"]),
            "source_data_date": as_of,
            "actual_source_date": payload.get("actual_source_date") or as_of,
            "coverage_status": "complete",
            "payload": payload,
        })
    return records


def _buffett_guidance(records: list[dict[str, Any]], portfolio: Mapping[str, Any]) -> dict[str, Any]:
    """Translate deterministic research evidence into reusable Buffett-style guidance."""
    holdings = {str(item.get("target_id")) for item in portfolio.get("holdings", [])}
    actions: list[dict[str, Any]] = []
    for record in sorted(
        records,
        key=lambda item: (
            item.get("decision") == "research_candidate",
            float(item.get("soft_score") or item.get("quality_score") or -1),
        ),
        reverse=True,
    )[:12]:
        symbol = str(record["target_id"])
        decision = str(record.get("decision") or "insufficient_data")
        concerns = [
            *(str(value) for value in record.get("sell_triggers", []) or []),
            *(str(value) for value in record.get("risk_flags", []) or []),
        ]
        if symbol in holdings:
            stance = "长期持有复核"
            recommendation = "继续以经营质量为核心复核；估值上升或排名回落本身不触发退出。"
        elif decision == "research_candidate" and record.get("entry_eligible"):
            stance = "优先研究候选"
            recommendation = "先确认能理解商业模式、资本回报可持续和合理价格，再决定是否纳入长期组合。"
        elif decision == "watchlist":
            stance = "观察名单"
            recommendation = "保持跟踪，等待经营质量、估值或流动性约束改善；不因短期波动追逐。"
        else:
            stance = "暂缓研究"
            recommendation = "核心数据或风险约束未满足，遵循宁缺毋滥原则，不纳入长期组合。"
        actions.append(
            {
                "target_id": symbol,
                "stance": stance,
                "recommendation": recommendation,
                "quality_score": record.get("soft_score", record.get("quality_score")),
                "valuation_score": record.get("valuation_score"),
                "coverage_ratio": record.get("coverage_ratio"),
                "industry": record.get("industry"),
                "concerns": concerns,
            }
        )
    cash_weight = float(portfolio.get("cash_weight") or 0.0)
    cash_guidance = (
        "保留现金是有效选择：可投资机会不足或受组合约束时，不为满仓而降低质量标准。"
        if cash_weight > 0
        else "组合已按当前约束配置；后续优先复核经营质量，而不是因价格短期变化频繁换仓。"
    )
    return {
        "method": "buffett_style_quantitative_research_guidance",
        "overall": "以可理解的生意、可持续资本回报、稳健现金创造、合理价格和长期持有为优先级。",
        "principles": [
            "经营质量优先于短期价格波动",
            "估值是新入门槛，不因估值上升自动卖出健康持仓",
            "集中但受行业和银行权重约束",
            "证据不足时保留现金并继续研究",
        ],
        "portfolio": {
            "holding_count": len(holdings),
            "cash_weight": cash_weight,
            "cash_guidance": cash_guidance,
        },
        "research_actions": actions,
        "boundary": "这是基于点时量化证据的研究建议，不构成买卖指令、收益承诺或个性化投资建议。",
    }


def _apply_capacity_gate(
    payloads: list[dict[str, Any]], liquidity: pd.DataFrame, *, capital: float, thresholds: Mapping[str, Any]
) -> None:
    grouped: dict[str, tuple[float | None, int]] = {}
    if liquidity is not None and not liquidity.empty and {"symbol", "turnover"}.issubset(liquidity.columns):
        work = liquidity.copy()
        work["turnover"] = pd.to_numeric(work["turnover"], errors="coerce")
        for symbol, group in work.dropna(subset=["symbol", "turnover"]).groupby("symbol"):
            grouped[str(symbol)] = (float(group["turnover"].median()), int(group["turnover"].count()))
    for payload in payloads:
        symbol = str(payload.get("target_id", ""))
        median_turnover, valid_days = grouped.get(symbol, (None, 0))
        evidence = capacity_check(
            capital=capital,
            median_turnover=median_turnover,
            valid_days=valid_days,
            thresholds=thresholds,
        )
        payload["liquidity_capacity"] = "ok" if evidence["capacity_ok"] else evidence["reason"]
        payload["liquidity_evidence"] = evidence
        if not evidence["capacity_ok"] and payload.get("decision") == "research_candidate":
            payload["entry_eligible"] = False
            payload["decision"] = "watchlist"


def _apply_market_status_gate(payloads: list[dict[str, Any]], snapshot: pd.DataFrame) -> None:
    """Block risky new entries while allowing existing holdings to be reviewed."""
    flags_by_symbol: dict[str, set[str]] = {}
    if snapshot is not None and not snapshot.empty and {"symbol", "risk_flags"}.issubset(snapshot.columns):
        for _, row in snapshot.iterrows():
            raw_flags = row.get("risk_flags") or []
            if isinstance(raw_flags, str):
                raw_flags = [raw_flags]
            flags_by_symbol[str(row["symbol"])] = set(str(flag) for flag in raw_flags)
    for payload in payloads:
        symbol = str(payload.get("target_id", ""))
        flags = flags_by_symbol.get(symbol)
        if flags is None:
            payload["market_status"] = "not_observed"
            payload["risk_flags"] = ["market_status_unobserved"]
            if payload.get("decision") == "research_candidate":
                payload["entry_eligible"] = False
                payload["decision"] = "watchlist"
            continue
        payload["market_status"] = "risk" if flags else "normal"
        payload["risk_flags"] = sorted(flags)
        if flags & {"st_risk", "suspension", "delisting_risk"}:
            payload["entry_eligible"] = False
            if payload.get("decision") == "research_candidate":
                payload["decision"] = "watchlist"
        if flags & {"st_risk", "delisting_risk"}:
            payload.setdefault("sell_triggers", []).extend(sorted(flags & {"st_risk", "delisting_risk"}))


def _apply_soft_financial_ranking(
    payloads: list[dict[str, Any]], *, review_top: int = 50
) -> list[dict[str, Any]]:
    """Replace financial hard gates with the documented continuous ranking."""
    if __package__ in {None, ""}:
        from scripts.soft_scorer import score_payloads
    else:
        from .soft_scorer import score_payloads

    by_symbol = {str(payload.get("target_id")): payload for payload in payloads}
    ranked: list[dict[str, Any]] = []
    severe_reasons = {
        "audit_opinion",
        "normalized_profit_nonpositive",
        "debt_to_profit_at_least_6",
        "quarterly_profit_or_eps_nonpositive",
    }
    for rank, score in enumerate(score_payloads(payloads), start=1):
        payload = by_symbol[score["symbol"]]
        legacy_quality = payload.get("quality_score")
        payload.update(score)
        payload["target_id"] = score["symbol"]
        payload["legacy_quality_score"] = legacy_quality
        payload["quality_score"] = score["total_score"]
        payload["soft_score"] = score["total_score"]
        payload["soft_rank"] = rank
        blocked = bool(severe_reasons.intersection(payload.get("sell_triggers") or []))
        if blocked or not score["soft_eligible"]:
            payload["decision"] = "reject" if blocked else "insufficient_data"
            payload["entry_eligible"] = False
        elif rank <= review_top:
            payload["decision"] = "research_candidate"
            payload["entry_eligible"] = True
        else:
            payload["decision"] = "watchlist"
            payload["entry_eligible"] = False
        ranked.append(payload)
    return ranked


def run(input_data: Mapping[str, Any], config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    validate_input(input_data)
    options = dict(config or {})
    _validate_config(options)
    as_of = str(input_data["as_of_date"])
    preset = options.get("preset")
    if preset is not None and str(preset) not in {"default", "buffett_strict"}:
        raise ValueError(f"unknown preset: {preset!r}; expected 'default' or 'buffett_strict'")
    selection_mode = str(options.get("selection_mode", "soft"))
    if selection_mode not in {"soft", "hard"}:
        raise ValueError("selection_mode must be 'soft' or 'hard'")
    base_thresholds = BUFFETT_STRICT_THRESHOLDS if selection_mode == "hard" and str(preset) == "buffett_strict" else DEFAULT_THRESHOLDS
    thresholds = {**base_thresholds, **dict(options.get("thresholds", {}))}
    batch_size = int(options.get("batch_size", 50))
    explicit = input_data.get("symbols")
    index_symbol = input_data.get("index_symbol")
    details = pd.DataFrame()
    if explicit:
        symbols = sorted(set(explicit))
    elif index_symbol:
        symbols = data_pipeline.discover_symbols(as_of, str(index_symbol))
    else:
        symbols, details = data_pipeline.discover_all_a(as_of)
    try:
        # Reuse immutable market-data responses across repeated all-A builds;
        # the cache contains no credentials and is released from process state
        # in the finally block below.
        data_pipeline.configure_cache(DEFAULT_CACHE)
        payloads, _ = screen_symbols(symbols, as_of, thresholds=thresholds, batch_size=batch_size)
        if selection_mode == "soft":
            payloads = _apply_soft_financial_ranking(
                payloads, review_top=max(1, int(options.get("soft_review_top", 50)))
            )
        try:
            liquidity = data_pipeline.fetch_liquidity_observations(symbols, as_of, batch_size=batch_size)
        except Exception:
            liquidity = pd.DataFrame()
        _apply_capacity_gate(
            payloads,
            liquidity,
            capital=float(options.get("reference_capital", 10_000_000.0)),
            thresholds=thresholds,
        )
        try:
            market_status = data_pipeline.fetch_market_status_snapshot(symbols, as_of)
        except Exception:
            market_status = pd.DataFrame()
        _apply_market_status_gate(payloads, market_status)
        quantitative = {str(item["target_id"]): item for item in payloads}
        if not details.empty and "symbol" in details and "universe_status" in details:
            for symbol, payload in quantitative.items():
                payload["universe_status"] = str(details.loc[details["symbol"].eq(symbol), "universe_status"].iloc[-1]) if not details.loc[details["symbol"].eq(symbol)].empty else "point_in_time_valid"
        records = _records(list(quantitative.values()), as_of)
        prior_state = dict(options["portfolio_state"]) if "portfolio_state" in options else load_portfolio_state(options.get("output_path") or DEFAULT_OUTPUT, signal_date=as_of)
        execution_date = as_of
        try:
            calendar_end = (datetime.strptime(as_of, "%Y%m%d") + timedelta(days=10)).strftime("%Y%m%d")
            execution_date = next_open_date(data_pipeline.fetch_trade_calendar(as_of, calendar_end), as_of) or as_of
        except Exception:
            # A signal remains inspectable even when the optional calendar
            # endpoint is temporarily unavailable; it cannot create an order.
            execution_date = as_of
        materialized_portfolio = None
        if "portfolio_state" not in options:
            materialized_portfolio = load_materialized_portfolio(
                options.get("output_path") or DEFAULT_OUTPUT,
                signal_date=as_of,
                execution_date=execution_date,
            )
        execution_prices: dict[str, float] = {}
        if options.get("capital") is not None:
            try:
                execution_prices = data_pipeline.fetch_execution_prices(symbols, execution_date)
            except Exception:
                execution_prices = {}
        portfolio = build_portfolio([record["payload"] for record in records], signal_date=as_of, execution_date=execution_date, prior_state=prior_state, capital=options.get("capital"), execution_prices=execution_prices, quality_exit_min=thresholds.get("quality_exit_min"), qualitative_required=False)
        if materialized_portfolio is not None:
            portfolio = materialized_portfolio
        portfolio_records: list[dict[str, Any]] = []
        for holding in portfolio.get("holdings", []):
            portfolio_records.append({"trade_date": execution_date, "target_id": holding["target_id"], "result_type": "portfolio_target_weight", "result_value": f"{float(holding.get('actual_weight', holding.get('policy_weight', 0))):.10f}", "source_data_date": as_of, "actual_source_date": execution_date, "coverage_status": "complete", "payload": holding})
        portfolio_records.append({"trade_date": execution_date, "target_id": "CASH.CNY", "result_type": "portfolio_target_weight", "result_value": f"{float(portfolio.get('cash_weight', 1)):.10f}", "source_data_date": as_of, "actual_source_date": execution_date, "coverage_status": "complete", "payload": {"target_id": "CASH.CNY", "target_weight": portfolio.get("cash_weight", 1), "cash_leg": "511880.SH"}})
        portfolio_records.append({"trade_date": execution_date, "target_id": str(portfolio["strategy_id"]), "result_type": "portfolio_summary", "result_value": f"{float(portfolio.get('cash_weight', 1)):.10f}", "source_data_date": as_of, "actual_source_date": execution_date, "coverage_status": "complete", "payload": portfolio})
        for transition in portfolio.get("transitions", []):
            portfolio_records.append({"trade_date": execution_date, "target_id": str(transition["target_id"]), "result_type": "portfolio_state_transition", "result_value": str(transition["review_action"]), "source_data_date": as_of, "actual_source_date": execution_date, "coverage_status": "complete", "payload": transition})
        universe_payload = {"universe": "all_a" if not explicit and not index_symbol else "subset", "provider_scope": "SH/SZ only; BJ unavailable", "as_of_date": as_of, "count": len(symbols), "historical_delisted_included": not bool(explicit or index_symbol)}
        portfolio_records.append({"target_id": "UNIVERSE.ALL_A", "result_type": "universe_summary", "result_value": str(len(symbols)), "source_data_date": as_of, "actual_source_date": as_of, "coverage_status": "complete", "payload": universe_payload})
        counts = Counter(item["decision"] for item in records)
        guidance = _buffett_guidance(records, portfolio)
        output: dict[str, Any] = {"build_id": BUILD_ID, "build_name": BUILD_NAME, "data_version": DATA_VERSION, "schema_version": SCHEMA_VERSION, "as_of_date": as_of, "status": "ok", "universe": universe_payload, "source": {"provider": "panda_data", "sdk_version": sdk_version(), "market": "cn", "apis": ["get_stock_detail", "get_fina_reports", "get_stock_daily", "get_stock_daily_post", "get_audit_opinion", "get_industry_constituents"]}, "summary": {"total": len(records), **{key: counts.get(key, 0) for key in ("research_candidate", "watchlist", "manual_review", "reject", "insufficient_data")}}, "decision_framework": {"selection_mode": selection_mode, "financial_threshold_mode": "soft_anchors" if selection_mode == "soft" else "hard_gates", "automated_scope": "quantitative queue and portfolio state", "research_checklist": RESEARCH_CHECKLIST, "portfolio_rule": "dynamic event-driven long-term state machine; no minimum holding period; no orders"}, "records": records, "portfolio": portfolio, "buffett_guidance": guidance}
        if options.get("materialize"):
            if not records:
                raise PandaDataError("股票池为空，拒绝覆盖生产文件")
            if explicit or index_symbol:
                raise PandaDataError("正式 V9 物化必须使用完整 all_a 股票池，子集结果只能研究不落盘")
            frame = build_production_frame(build_id=BUILD_ID, build_name=BUILD_NAME, trade_date=as_of, records=records + portfolio_records, data_version=DATA_VERSION)
            write_versioned_production(frame, options.get("output_path") or DEFAULT_OUTPUT, DATA_VERSION)
            output["production_path"] = str(options.get("output_path") or DEFAULT_OUTPUT)
        return output
    finally:
        data_pipeline.configure_cache(None)
        clear_process_credentials()


def main() -> int:
    parser = argparse.ArgumentParser(description="Q44 V9.4 all-A Buffett research queue")
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--materialize", action="store_true")
    args = parser.parse_args()
    result = run({"as_of_date": args.as_of_date, **({"symbols": args.symbols} if args.symbols else {})}, {"materialize": args.materialize})
    print(json.dumps({key: value for key, value in result.items() if key not in {"records", "portfolio"}}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
