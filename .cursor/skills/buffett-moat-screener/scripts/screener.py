"""Reusable point-in-time Q44 screening orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from . import data_pipeline
from .scoring import evaluate_buffett_company, rank_buffett_candidates
from .v9_engine import quarterly_safety_status


def _normalise_quarterly(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty or "quarter" not in frame:
        return pd.DataFrame()
    work = frame.copy()
    for target, sources in data_pipeline.CANONICAL_FIELDS.items():
        if target in {"symbol", "year"}:
            continue
        values = pd.Series(pd.NA, index=work.index, dtype="object")
        for source in sources:
            if source in work:
                values = values.fillna(work[source])
        work[target] = values
    return work


def screen_symbols(
    symbols: list[str],
    as_of: str,
    *,
    thresholds: Mapping[str, float],
    batch_size: int,
    raw_financials: pd.DataFrame | None = None,
    memberships: pd.DataFrame | None = None,
    price_frame: pd.DataFrame | None = None,
    audit_histories: Mapping[str, list[dict[str, Any]]] | None = None,
    audit_gate: bool = True,
    quarterly_gate: bool = True,
    annual_frame: pd.DataFrame | None = None,
    annual_conflicts: list[dict[str, Any]] | None = None,
    quarterly_frame: pd.DataFrame | None = None,
) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    raw = (
        data_pipeline.fetch_financial_history(symbols, as_of, years=12, batch_size=batch_size)
        if raw_financials is None
        else raw_financials[raw_financials["symbol"].map(data_pipeline.clean_symbol).isin(symbols)].copy()
    )
    selected, conflicts = (
        (annual_frame, list(annual_conflicts or []))
        if annual_frame is not None
        else data_pipeline.select_atomic_annual_revisions(raw, as_of)
    )
    prices = (
        data_pipeline.fetch_prices(symbols, as_of)
        if price_frame is None
        else price_frame[
            price_frame["symbol"].map(data_pipeline.clean_symbol).isin(symbols)
            & (price_frame["date"].astype(str).str.replace("-", "", regex=False) <= as_of)
        ].copy()
    )
    normalized = data_pipeline.normalize_annual_history(selected, prices)
    quarterly = _normalise_quarterly(raw) if quarterly_frame is None else quarterly_frame
    # Full-A replay evaluates thousands of symbols on each signal date.
    # Group once up front instead of scanning the complete table per symbol.
    annual_by_symbol = (
        {str(symbol): frame.copy() for symbol, frame in normalized.groupby("symbol", sort=False)}
        if not normalized.empty and "symbol" in normalized else {}
    )
    quarterly_by_symbol = (
        {str(symbol): frame.copy() for symbol, frame in quarterly.groupby("symbol", sort=False)}
        if not quarterly.empty and "symbol" in quarterly else {}
    )

    industry_history = (
        data_pipeline.fetch_historical_industries(symbols)
        if memberships is None
        else memberships
    )
    industries = data_pipeline.historical_industry_map(industry_history, as_of)

    def evaluate(symbol: str, audit_history: list[dict[str, Any]]) -> dict[str, Any]:
        company = annual_by_symbol.get(symbol, normalized.iloc[0:0])
        latest_year = int(company["year"].max()) if not company.empty else int(as_of[:4]) - 1
        payload = evaluate_buffett_company(
            symbol,
            company,
            industry=industries.get(symbol, ""),
            audit_history=audit_history,
            as_of_year=latest_year,
            thresholds=thresholds,
            audit_gate=audit_gate,
        )
        safety = quarterly_safety_status(
            quarterly_by_symbol.get(symbol, quarterly.iloc[0:0]),
            symbol=None,
            as_of=as_of,
            max_age_days=int(thresholds.get("quarterly_stale_days", 180)),
        ) if quarterly_gate else {"status": "not_backtested"}
        payload["quarterly_safety_status"] = safety.get("status", "missing")
        payload["quarterly_ttm"] = safety.get("ttm", {})
        payload["event_type"] = "quarterly_report" if quarterly_gate and safety.get("quarter") else "annual_report"
        payload["event_date"] = str(safety.get("event_date") or payload.get("actual_source_date") or as_of)
        payload["event_revision_date"] = safety.get("as_of_revision")
        if quarterly_gate and safety.get("status") == "warning":
            payload.setdefault("sell_triggers", []).append("quarterly_profit_or_eps_nonpositive")
            payload["hold_status"] = "exit"
        elif quarterly_gate and safety.get("status") == "missing":
            payload.setdefault("research_gaps", []).append("季度 TTM 安全字段缺失")
        elif quarterly_gate and safety.get("status") == "stale":
            payload.setdefault("research_gaps", []).append("季度 TTM 证据已过期，只允许保留持仓并冻结加仓")
            payload["entry_eligible"] = False
            if payload.get("decision") == "research_candidate":
                payload["decision"] = "watchlist"
        symbol_conflicts = [row for row in conflicts if row["symbol"] == symbol]
        if symbol_conflicts:
            payload["research_gaps"].append("Same-date filing revisions conflict; latest atomic row retained.")
            payload["revision_conflicts"] = symbol_conflicts
        return payload

    preliminary: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        company = annual_by_symbol.get(symbol, normalized.iloc[0:0])
        latest_year = int(company["year"].max()) if not company.empty else int(as_of[:4]) - 1
        provisional = evaluate(
            symbol, [{"year": latest_year, "status": "unqualified"}]
        )
        preliminary[symbol] = provisional
    audit_candidates: dict[str, int] = {}
    for symbol, payload in preliminary.items():
        minimum = thresholds[
            "bank_quality_score_min" if payload.get("special_case") == "bank_roa" else "quality_score_min"
        ]
        if payload.get("special_case") in {"financial", "cyclical"} or payload.get("quality_score", 0) < minimum:
            continue
        company = annual_by_symbol.get(symbol, normalized.iloc[0:0])
        latest_year = int(company["year"].max()) if not company.empty else int(as_of[:4]) - 1
        audit_candidates[symbol] = latest_year
    if audit_histories is None:
        audit_histories = data_pipeline.fetch_audit_histories(
            audit_candidates, as_of=as_of, years=3, batch_size=max(1, min(batch_size, 50))
        ) if audit_candidates else {}
    else:
        # The caller may prefetch through the final date.  Apply the signal
        # date here so a later audit opinion cannot enter an earlier screen.
        audit_histories = {
            symbol: [
                dict(row) for row in audit_histories.get(symbol, [])
                if str(row.get("published_at") or "") <= str(as_of)
            ]
            for symbol in audit_candidates
        }
    for symbol in audit_candidates:
        preliminary[symbol] = evaluate(symbol, audit_histories.get(symbol, []))
    return rank_buffett_candidates(list(preliminary.values())), normalized
