"""Concentrated, stateful Buffett-style portfolio construction."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from .core import DATA_VERSION
from .v9_engine import conviction_score, opportunity_replacement, policy_ceiling, transition_holding


STRATEGY_ID = "Q44-BUFFETT-A-SHARE-V9"
MAX_SLOTS = 8
POLICY_WEIGHTS = (0.20, 0.15, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10)
LOT_SIZE = 100
BANK_WEIGHT_MAX = 0.15
INDUSTRY_WEIGHT_MAX = 0.30
STRUCTURAL_WARNING_REASONS = {
    "cash_conversion_3y_below_40pct",
    "owner_earnings_negative_years",
    "debt_to_profit_between_4_and_6",
    "data_confidence_decline",
    "quality_score_soft_warning",
}


def _structural_warning(evidence: Mapping[str, Any]) -> bool:
    """Return whether a warning is operating evidence, rather than score drift."""
    reasons = evidence.get("warning_reasons")
    if reasons is None:
        # Preserve compatibility with older materialized records that only
        # carried hold_status and therefore cannot distinguish the two kinds.
        return evidence.get("hold_status") == "warning"
    return bool(STRUCTURAL_WARNING_REASONS.intersection(str(item) for item in reasons))


def _number(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def _candidate_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    """Order new ideas by conviction, then business quality before price.

    Valuation remains an entry gate and a tie-breaker.  It must not let a
    cheaper but materially weaker business outrank a durable compounder.
    """
    # Once qualitative evidence is available, conviction is the portfolio
    # decision variable.  Historical quantitative replay supplies a clearly
    # labelled quantitative proxy in the same field.  Quality remains the
    # first tie-breaker so a cheap but weaker business cannot win on price.
    return (
        -_number(record.get("conviction_score"), -math.inf),
        -_number(record.get("quality_score"), -math.inf),
        -_number((record.get("metrics") or {}).get("roe_floor_pct"), -math.inf),
        -_number((record.get("metrics") or {}).get("roic_proxy_floor_pct"), -math.inf),
        -_number((record.get("metrics") or {}).get("owner_earnings_positive_year_ratio"), -math.inf),
        -_number(record.get("qualitative_score"), -math.inf),
        -_number(record.get("valuation_score"), -math.inf),
        -_number(record.get("cash_earnings_yield_proxy"), -math.inf),
        str(record.get("target_id", "")),
    )


def load_portfolio_state(path: str | Path, *, signal_date: str) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        return {"holdings": [], "state_origin": "cash_start"}
    frame = pd.read_parquet(source)
    required = {"trade_date", "data_version", "result_type", "target_id", "result_json"}
    if frame.empty or not required.issubset(frame.columns):
        return {"holdings": [], "state_origin": "cash_start"}
    eligible = frame[
        (frame["data_version"].astype(str) == DATA_VERSION)
        & (frame["result_type"].astype(str) == "portfolio_target_weight")
        & (frame["trade_date"].astype(str) < signal_date)
        & (frame["target_id"].astype(str) != "CASH.CNY")
    ]
    if eligible.empty:
        return {"holdings": [], "state_origin": "cash_start"}
    latest_date = eligible["trade_date"].astype(str).max()
    latest = eligible[eligible["trade_date"].astype(str) == latest_date]
    holdings = []
    for _, row in latest.iterrows():
        payload = json.loads(str(row["result_json"]))
        if isinstance(payload, dict):
            holdings.append(payload)
    return {"holdings": sorted(holdings, key=lambda item: item["target_id"]), "state_origin": "production", "state_date": latest_date}


def load_materialized_portfolio(
    path: str | Path, *, signal_date: str, execution_date: str
) -> dict[str, Any] | None:
    source = Path(path)
    if not source.exists():
        return None
    frame = pd.read_parquet(source)
    required = {"trade_date", "data_version", "result_type", "result_json"}
    if frame.empty or not required.issubset(frame.columns):
        return None
    rows = frame[
        (frame["data_version"].astype(str) == DATA_VERSION)
        & (frame["result_type"].astype(str) == "portfolio_summary")
        & (frame["trade_date"].astype(str) == execution_date)
    ]
    for payload_text in reversed(rows["result_json"].astype(str).tolist()):
        payload = json.loads(payload_text)
        if isinstance(payload, dict) and str(payload.get("signal_date")) == signal_date:
            return {**payload, "state_origin": "materialized_current_review"}
    return None


def mark_to_market_state(
    state: Mapping[str, Any],
    stock_return_factors: Mapping[str, float],
    *,
    cash_return_factor: float = 1.0,
) -> dict[str, Any]:
    holdings = [dict(row) for row in state.get("holdings", [])]
    invested = sum(_number(row.get("actual_weight", row.get("policy_weight")), 0.0) for row in holdings)
    cash_weight = max(0.0, 1.0 - invested)
    values = []
    for row in holdings:
        weight = _number(row.get("actual_weight", row.get("policy_weight")), 0.0)
        factor = _number(stock_return_factors.get(str(row["target_id"])), 1.0)
        values.append(weight * max(factor, 0.0))
    cash_value = cash_weight * max(_number(cash_return_factor, 1.0), 0.0)
    total = sum(values) + cash_value
    if total > 0:
        for row, value in zip(holdings, values):
            row["actual_weight"] = value / total
    return {
        **dict(state),
        "holdings": holdings,
        "cash_weight": cash_value / total if total > 0 else 1.0,
        "state_origin": f"{state.get('state_origin', 'provided')}_marked_to_market",
    }


def _trim_drift_caps(holdings: list[dict[str, Any]], transitions: list[dict[str, Any]]) -> None:
    for holding in holdings:
        if _number(holding.get("actual_weight"), 0.0) > 0.30:
            holding["actual_weight"] = 0.25
            holding["policy_weight"] = min(_number(holding.get("policy_weight"), 0.25), 0.25)
            holding["target_weight"] = holding["policy_weight"]
            holding["review_action"] = "risk_trim"
            transitions.append({"target_id": holding["target_id"], "review_action": "risk_trim", "reason": "single_weight_above_30pct"})
    industry_totals: dict[str, float] = {}
    for holding in holdings:
        industry = str(holding.get("industry") or "")
        industry_totals[industry] = industry_totals.get(industry, 0.0) + _number(holding.get("actual_weight"), 0.0)
    for industry, total in industry_totals.items():
        if not industry or total <= 0.40:
            continue
        members = sorted(
            (holding for holding in holdings if str(holding.get("industry") or "") == industry),
            key=lambda holding: _number(holding.get("actual_weight"), 0.0),
            reverse=True,
        )
        excess = total - 0.35
        for holding in members:
            if excess <= 0:
                break
            current = _number(holding.get("actual_weight"), 0.0)
            reduction = min(excess, max(0.0, current - 0.05))
            holding["actual_weight"] = current - reduction
            holding["policy_weight"] = min(_number(holding.get("policy_weight"), current), holding["actual_weight"])
            holding["target_weight"] = holding["policy_weight"]
            holding["review_action"] = "risk_trim"
            excess -= reduction
            transitions.append({"target_id": holding["target_id"], "review_action": "risk_trim", "reason": "industry_weight_above_40pct"})


def build_portfolio(
    records: Sequence[Mapping[str, Any]],
    *,
    signal_date: str,
    execution_date: str,
    prior_state: Mapping[str, Any] | None = None,
    capital: float | None = None,
    execution_prices: Mapping[str, float] | None = None,
    qualitative_required: bool = False,
    quality_exit_min: float | None = None,
) -> dict[str, Any]:
    by_symbol = {str(record["target_id"]): dict(record) for record in records}
    previous = list((prior_state or {}).get("holdings", []))
    holdings: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []

    for previous_holding in previous:
        symbol = str(previous_holding["target_id"])
        evidence = by_symbol.get(symbol)
        warning_count = int(previous_holding.get("annual_warning_count", 0))
        if evidence is None:
            # A transport or data-service outage is not evidence that the thesis is
            # broken.  Preserve the position and freeze additions until a
            # dated fundamental event arrives; never force a sale merely
            # because two refreshes were unavailable.
            action, reason = "warning_hold", "current_evidence_missing_no_forced_exit"
        elif evidence.get("sell_triggers") or evidence.get("serious_flags"):
            reasons = [*(evidence.get("sell_triggers") or []), *(evidence.get("serious_flags") or [])]
            transitions.append({"target_id": symbol, "review_action": "exit", "reason": ",".join(reasons)})
            continue
        elif evidence.get("qualitative_verdict") == "reject":
            transitions.append({"target_id": symbol, "review_action": "exit", "reason": "qualitative_serious_red_flag"})
            continue
        elif quality_exit_min is not None and _number(evidence.get("quality_score"), math.inf) < float(quality_exit_min):
            transitions.append({"target_id": symbol, "review_action": "exit", "reason": "configured_quality_floor_breached"})
            continue
        elif evidence.get("decision") == "insufficient_data":
            # Missing filings or stale feeds are
            # not proof that the investment thesis broke. Freeze additions
            # and preserve the holding until dated evidence arrives.
            action, reason = "warning_hold", "evidence_insufficient_no_forced_exit"
            holding = {
                **dict(previous_holding),
                "annual_warning_count": warning_count,
                "review_action": action,
                "policy_weight": _number(previous_holding.get("policy_weight", previous_holding.get("target_weight")), 0.0),
                "actual_weight": _number(previous_holding.get("actual_weight", previous_holding.get("policy_weight")), 0.0),
            }
            holding["target_weight"] = holding["policy_weight"]
            if evidence:
                holding["evidence"] = evidence
                for field in ("quality_score", "qualitative_score", "qualitative_confidence", "valuation_score", "conviction_score", "industry", "special_case"):
                    if field in evidence:
                        holding[field] = evidence.get(field)
            holdings.append(holding)
            transitions.append({"target_id": symbol, "review_action": action, "reason": reason})
            continue
        elif evidence.get("hold_status") == "warning" and _structural_warning(evidence):
            warning_count += 1
            if warning_count >= 2:
                transitions.append({"target_id": symbol, "review_action": "exit", "reason": "two_consecutive_quality_warnings"})
                continue
            action, reason = "warning_hold", "first_quality_warning"
        elif evidence.get("hold_status") == "warning":
            # A softer score is a prompt for research and a freeze on
            # additions, not proof that the business thesis is broken.
            warning_count = 0
            action, reason = "warning_hold", "quality_score_soft_warning_no_forced_exit"
        else:
            warning_count = 0
            action = "hold"
            reason = "valuation_does_not_force_sale" if evidence and not evidence.get("entry_eligible", False) else "quality_thesis_intact"
        holding = {
            **dict(previous_holding),
            "annual_warning_count": warning_count,
            "review_action": action,
            "policy_weight": _number(previous_holding.get("policy_weight", previous_holding.get("target_weight")), 0.0),
            "actual_weight": _number(previous_holding.get("actual_weight", previous_holding.get("policy_weight")), 0.0),
        }
        holding["target_weight"] = holding["policy_weight"]
        if evidence:
            for field in (
                "quality_score",
                "qualitative_score",
                "qualitative_confidence",
                "valuation_score",
                "conviction_score",
                "industry",
                "special_case",
            ):
                if field in evidence:
                    holding[field] = evidence.get(field)
            ceiling = policy_ceiling(evidence.get("conviction_score"))
            # A missing or newly expensive valuation must not erase the
            # policy ceiling earned by an existing holding.  It blocks new
            # entry, while a healthy thesis may still receive dated
            # evidence-driven reinvestment below that ceiling.
            prior_ceiling = _number(previous_holding.get("policy_ceiling"), 0.0)
            if ceiling <= 0.0 and prior_ceiling > 0.0:
                ceiling = prior_ceiling
            if evidence.get("special_case") == "bank_roa":
                ceiling = min(ceiling, BANK_WEIGHT_MAX)
            holding["policy_ceiling"] = ceiling
            holding["evidence"] = evidence
        holdings.append(holding)
        transitions.append({"target_id": symbol, "review_action": action, "reason": reason})

    _trim_drift_caps(holdings, transitions)
    held_symbols = {holding["target_id"] for holding in holdings}
    ranked = sorted(
        (dict(record) for record in records
         if record.get("entry_eligible")
         and record.get("decision") == "research_candidate"
         and (not qualitative_required or (
             record.get("qualitative_verdict", "qualitative_pending") == "approve"
             and _number(record.get("qualitative_confidence"), 0.0) >= 75.0
         ))
         and record.get("special_case") not in {"financial", "cyclical"}
         and not set(record.get("risk_flags") or ()) & {"st_risk", "suspension", "delisting_risk"}
         and record.get("liquidity_capacity", "ok") not in {"insufficient", "liquidity_or_capacity_insufficient"}),
        key=_candidate_key,
    )
    bank_used = any(holding.get("special_case") == "bank_roa" for holding in holdings)
    industry_policy: dict[str, float] = {}
    for holding in holdings:
        industry = str(holding.get("industry") or "")
        industry_policy[industry] = industry_policy.get(industry, 0.0) + _number(holding.get("policy_weight"), 0.0)

    # Add only to an existing healthy position with a dated quality ceiling.
    # Valuation remains an entry gate for new names; it does not erase a
    # ceiling already earned by an existing holding.  This is evidence-driven
    # capital deployment, not an annual rank rebalance; unused capacity remains
    # cash when constraints bind.
    for holding in sorted(holdings, key=_candidate_key):
        evidence = by_symbol.get(str(holding["target_id"]))
        if not evidence:
            continue
        valuation_entry_ok = bool(evidence.get("entry_eligible"))
        healthy_existing = (
            evidence.get("hold_status") == "healthy"
            and not evidence.get("sell_triggers")
            and not evidence.get("serious_flags")
            and _number(holding.get("policy_ceiling"), 0.0) > 0.0
        )
        if not valuation_entry_ok and not healthy_existing:
            continue
        if qualitative_required and not (
            evidence.get("qualitative_verdict") == "approve"
            and _number(evidence.get("qualitative_confidence"), 0.0) >= 75.0
        ):
            continue
        current_policy = _number(holding.get("policy_weight"), 0.0)
        ceiling = policy_ceiling(evidence.get("conviction_score"))
        if not valuation_entry_ok:
            ceiling = max(ceiling, _number(holding.get("policy_ceiling"), 0.0))
        if evidence.get("special_case") == "bank_roa":
            ceiling = min(ceiling, BANK_WEIGHT_MAX)
        if ceiling - current_policy < 0.02:
            continue
        industry = str(holding.get("industry") or evidence.get("industry") or "")
        remaining_industry = (
            max(0.0, INDUSTRY_WEIGHT_MAX - industry_policy.get(industry, 0.0))
            if industry else 1.0
        )
        remaining_cash = max(0.0, 1.0 - sum(_number(item.get("policy_weight"), 0.0) for item in holdings))
        increase = min(ceiling - current_policy, remaining_industry, remaining_cash)
        if increase < 0.02:
            continue
        holding["policy_weight"] = current_policy + increase
        holding["target_weight"] = holding["policy_weight"]
        holding["review_action"] = "add"
        industry_policy[industry] = industry_policy.get(industry, 0.0) + increase
        transitions.append({"target_id": holding["target_id"], "review_action": "add", "reason": "existing_quality_thesis_reinvestment_below_policy_ceiling" if not valuation_entry_ok else "dated_quality_confirmation_below_policy_ceiling", "increase": increase})

    # A full book may replace one position only when every Buffett-style
    # advantage is materially stronger.  This is an opportunity-cost decision,
    # never a rank refresh or age-based rebalance.
    if len(holdings) >= MAX_SLOTS and ranked:
        held = {str(item["target_id"]) for item in holdings}
        for newcomer in ranked:
            if str(newcomer["target_id"]) in held:
                continue
            incumbent = min(holdings, key=lambda item: _number(item.get("conviction_score"), -math.inf))
            if not opportunity_replacement(incumbent, newcomer, quantitative=not qualitative_required):
                continue
            holdings.remove(incumbent)
            incumbent_industry = str(incumbent.get("industry") or "")
            industry_policy[incumbent_industry] = max(0.0, industry_policy.get(incumbent_industry, 0.0) - _number(incumbent.get("policy_weight"), 0.0))
            bank_used = any(item.get("special_case") == "bank_roa" for item in holdings)
            transitions.append({"target_id": incumbent["target_id"], "review_action": "exit", "reason": "high_threshold_opportunity_replacement"})
            held.remove(str(incumbent["target_id"]))
            # Re-enter below using the normal policy-cap and industry checks.
            break

    for rank, record in enumerate(ranked):
        if len(holdings) >= MAX_SLOTS:
            break
        symbol = str(record["target_id"])
        if symbol in held_symbols:
            continue
        conviction = _number(record.get("conviction_score"), 0.0)
        base_weight = policy_ceiling(conviction)
        if base_weight <= 0:
            continue
        is_bank = record.get("special_case") == "bank_roa"
        if is_bank and bank_used:
            continue
        if is_bank:
            base_weight = min(base_weight, BANK_WEIGHT_MAX)
        industry = str(record.get("industry") or "")
        remaining_industry = (
            max(0.0, INDUSTRY_WEIGHT_MAX - industry_policy.get(industry, 0.0))
            if industry
            else 1.0
        )
        weight = min(base_weight, remaining_industry, max(0.0, 1.0 - sum(_number(item.get("policy_weight"), 0.0) for item in holdings)))
        if weight <= 0:
            continue
        holding = {
            "target_id": symbol,
            "rank": rank + 1,
            "holding_since": execution_date,
            "annual_warning_count": 0,
            "review_action": "enter",
            "policy_weight": weight,
            "target_weight": weight,
            "actual_weight": weight,
            "industry": industry,
            "special_case": record.get("special_case"),
            "quality_score": record.get("quality_score"),
            "qualitative_score": record.get("qualitative_score"),
            "qualitative_confidence": record.get("qualitative_confidence"),
            "valuation_score": record.get("valuation_score"),
            "conviction_score": record.get("conviction_score"),
            "policy_ceiling": base_weight,
            "evidence": record,
        }
        holdings.append(holding)
        held_symbols.add(symbol)
        industry_policy[industry] = industry_policy.get(industry, 0.0) + weight
        bank_used = bank_used or is_bank
        transitions.append({"target_id": symbol, "review_action": "enter", "reason": "quality_and_valuation_pass"})

    # Keep the materialized queue in the same order used for decisions.  A
    # quality-only display sort can otherwise make a lower-conviction holding
    # look like the first choice even though it was not selected that way.
    holdings.sort(key=_candidate_key)
    policy_invested = sum(_number(holding.get("policy_weight"), 0.0) for holding in holdings)
    prices = dict(execution_prices or {})
    invested_amount = 0.0
    if capital is not None:
        for holding in holdings:
            price = _number(prices.get(holding["target_id"]), math.nan)
            target_value = float(capital) * _number(holding.get("policy_weight"), 0.0)
            quantity = int(math.floor(target_value / price / LOT_SIZE) * LOT_SIZE) if math.isfinite(price) and price > 0 else 0
            value = quantity * price if quantity else 0.0
            holding.update(
                {
                    "reference_price": None if not math.isfinite(price) else price,
                    "reference_quantity": quantity,
                    "reference_value": value,
                }
            )
            invested_amount += value

    output: dict[str, Any] = {
        "strategy_id": STRATEGY_ID,
        "signal_date": signal_date,
        "execution_date": execution_date,
        "state_origin": (prior_state or {}).get("state_origin", "cash_start"),
        "slot_count": MAX_SLOTS,
        "holdings": holdings,
        "cash_weight": round(max(0.0, 1.0 - policy_invested), 10),
        "transitions": transitions,
        "evidence": {
            "selection": "quality_and_official-evidence_first_then_reasonable_price",
            "ranking": ["conviction score descending", "quality score descending", "valuation score descending"],
            "bank_cap": BANK_WEIGHT_MAX,
            "industry_cap": INDUSTRY_WEIGHT_MAX,
            "valuation_does_not_force_sale": True,
            "minimum_holding_period": None,
            "selection_basis": "point_in_time_quantitative_score",
        },
    }
    if capital is not None:
        output.update(
            {
                "capital": float(capital),
                "lot_size": LOT_SIZE,
                "cash_amount": round(float(capital) - invested_amount, 2),
            }
        )
    return output
