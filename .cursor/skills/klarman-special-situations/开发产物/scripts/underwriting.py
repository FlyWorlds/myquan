"""Fail-closed V7 underwriting with a compatibility path for V6 callers."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Iterable

try:
    from .evidence_model import EvidenceAtom, atom_mapping, compile_evidence
    from .policy import ResearchPolicy, default_policy
    from .valuation import value_distress, value_reorganization, value_spin_off
except ImportError:  # pragma: no cover - direct script execution
    from evidence_model import EvidenceAtom, atom_mapping, compile_evidence
    from policy import ResearchPolicy, default_policy
    from valuation import value_distress, value_reorganization, value_spin_off


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _verified(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("verified") is True


def _policy_for_legacy(
    policy: ResearchPolicy | None,
    minimum_margin_of_safety: float | None,
    failure_probability_stress: float | None,
) -> ResearchPolicy:
    result = policy or default_policy()
    overrides: dict[str, float] = {}
    if minimum_margin_of_safety is not None:
        overrides["minimum_margin_of_safety"] = float(minimum_margin_of_safety)
    if failure_probability_stress is not None:
        overrides["failure_probability_stress"] = float(failure_probability_stress)
    return result.with_overrides(**overrides) if overrides else result


def _atom_ready(atoms: Mapping[str, EvidenceAtom], field: str) -> bool:
    row = atoms.get(field)
    return row is not None and row.core


def _v7_underwriting(
    facts: Mapping[str, Any],
    *,
    situation_type: str,
    policy: ResearchPolicy,
    atoms: Iterable[EvidenceAtom | Mapping[str, Any]] | None,
    compiled_evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    raw_atoms = list(atoms or (compiled_evidence or {}).get("atoms", []))
    compiled = dict(compiled_evidence or compile_evidence(raw_atoms))
    usable_atoms = list(compiled.get("atoms", []))
    usable_atoms = [item if isinstance(item, EvidenceAtom) else EvidenceAtom.from_mapping(item) for item in usable_atoms]
    indexed = atom_mapping(usable_atoms)
    missing: list[str] = []

    def require(name: str, present: bool = True) -> None:
        if not present or not _atom_ready(indexed, name):
            missing.append(name)

    require("symbol", bool(facts.get("symbol")))
    require("market_price", _number(facts.get("market_price")) is not None)
    require("catalyst_verified", facts.get("catalyst_verified") is True)
    require("capital_structure_verified", facts.get("capital_structure_verified") is True)
    require("legal_accounting_verified", facts.get("legal_accounting_verified") is True)
    require("liquidity_verified", facts.get("liquidity_verified") is True)

    try:
        if situation_type == "reorganization":
            required = [
                "conditions_verified",
                "financing_verified",
                "approvals_verified",
                "termination_terms_verified",
                "expected_close_date",
            ]
            for name in required:
                require(name, bool(facts.get(name)))
            valuation = value_reorganization(facts, usable_atoms, policy)
        elif situation_type == "spin_off":
            for name in (
                "ownership_pct",
                "subsidiary_value",
                "remaining_business_value",
                "net_debt",
                "tax_leakage",
                "holdco_discount_pct",
                "fully_diluted_shares",
                "failure_value_per_share",
            ):
                require(name, _number(facts.get(name)) is not None)
            valuation = value_spin_off(facts, usable_atoms, policy)
        elif situation_type in {"distress", "distress_turnaround"}:
            categories = facts.get("asset_recovery_values")
            if not isinstance(categories, Mapping) or not categories:
                missing.append("asset_recovery_values")
            else:
                for key in categories:
                    require(f"asset_recovery_values.{key}", _number(categories[key]) is not None)
            for name in (
                "secured_debt",
                "priority_claims",
                "unsecured_debt",
                "contingent_liabilities",
                "restructuring_costs",
                "fully_diluted_shares",
            ):
                require(name, _number(facts.get(name)) is not None)
            valuation = value_distress(facts, usable_atoms, policy)
        else:
            missing.append("situation_type")
            valuation = {}
    except (TypeError, ValueError):
        valuation = {}
        missing.append("valuation_lineage")

    market_price = _number(facts.get("market_price"))
    conservative = _number(valuation.get("conservative_value"))
    failure = _number(valuation.get("failure_value"))
    if market_price is None:
        missing.append("market_price")
    if conservative is None or conservative <= 0:
        missing.append("conservative_value")
    if failure is None:
        missing.append("failure_value")
    margin = None
    if market_price and conservative and conservative > 0:
        margin = (conservative - market_price) / conservative
    if margin is None or margin < policy.minimum_margin_of_safety:
        missing.append("minimum_margin_of_safety")

    # Preserve ordering while making the report deterministic.
    missing = list(dict.fromkeys(missing))
    qualified = not missing
    status = "qualified_special_situation" if qualified else "underwriting_incomplete"
    permanent_loss = None if market_price is None or failure is None else max(0.0, (market_price - failure) / market_price)
    return {
        "underwriting_status": status,
        "qualification_reason": "all_required_gates_passed" if qualified else "missing_required_evidence",
        "policy_id": policy.policy_id,
        "knowledge_cutoff": compiled.get("knowledge_cutoff"),
        "evidence_manifest": compiled.get("evidence_manifest", {}),
        "klarman_gates": {
            "matrix": {name: {"required": True, "status": "missing" if name in missing else "pass"} for name in sorted(set(missing) | {"security_access", "catalyst", "capital_structure", "legal_accounting", "liquidity", "valuation", "failure_value", "minimum_margin_of_safety"})},
            "missing_required": missing,
        },
        "deal_terms": {
            key: facts.get(key)
            for key in ("conditions_verified", "financing_verified", "approvals_verified", "termination_terms_verified", "expected_close_date")
            if key in facts
        },
        "valuation": {
            **valuation,
            "market_price": market_price,
            "discount_to_conservative_value": margin,
            "upside_to_conservative_value": None if not market_price or conservative is None else conservative / market_price - 1,
            "minimum_margin_of_safety": policy.minimum_margin_of_safety,
        },
        "downside_case": {
            "break_value": failure,
            "permanent_loss_pct": permanent_loss,
            "failure_probability_stress": policy.failure_probability_stress,
            "stress_probability_source": "caller_policy",
        },
        "risk_budget_inputs": {
            "worst_case_loss_pct": permanent_loss,
            "dependency_tags": list(facts.get("dependency_tags") or []),
            "diversification_required": True,
        },
    }


def _legacy_underwriting(
    evidence: Mapping[str, Any],
    *,
    minimum_margin_of_safety: float | None,
    failure_probability_stress: float | None,
) -> dict[str, Any]:
    """Retain V6 semantics for existing callers and fixtures."""
    market_price = _number(evidence.get("market_price"))
    valuation = dict(evidence.get("valuation") or {})
    downside = dict(evidence.get("downside_case") or {})
    deal_terms = dict(evidence.get("deal_terms") or {})
    conservative_value = _number(valuation.get("conservative_value"))
    break_value = _number(downside.get("break_value"))
    discount = None
    upside = None
    if market_price and market_price > 0 and conservative_value and conservative_value > 0:
        discount = (conservative_value - market_price) / conservative_value
        upside = conservative_value / market_price - 1
    valuation.update({"market_price": market_price, "conservative_value": conservative_value, "discount_to_conservative_value": discount, "upside_to_conservative_value": upside, "minimum_margin_of_safety": minimum_margin_of_safety})
    permanent_loss = None if not market_price or break_value is None else max(0.0, (market_price - break_value) / market_price)
    downside.update({"break_value": break_value, "permanent_loss_pct": permanent_loss, "failure_probability_stress": failure_probability_stress, "stress_probability_source": "caller_assumption" if failure_probability_stress is not None else None})
    terms_verified = all((_number(deal_terms.get("consideration_value")) is not None, deal_terms.get("conditions_verified") is True, deal_terms.get("financing_verified") is True, bool(deal_terms.get("expected_close_date"))))
    gates = {"security_access": bool(evidence.get("symbol")) and market_price is not None, "catalyst": _verified(evidence.get("catalyst")), "deal_terms": terms_verified, "conservative_value": conservative_value is not None, "failure_value": break_value is not None, "capital_structure": _verified(evidence.get("capital_structure")), "legal_accounting": _verified(evidence.get("legal_accounting")), "liquidity": _verified(evidence.get("liquidity")), "minimum_margin_of_safety": minimum_margin_of_safety is not None}
    missing = [name for name, passed in gates.items() if not passed]
    status = "underwriting_incomplete"
    if not missing:
        status = "qualified_special_situation" if discount is not None and discount >= float(minimum_margin_of_safety) else "rejected"
    return {
        "underwriting_status": status,
        "qualification_reason": "all_required_gates_passed"
        if status == "qualified_special_situation"
        else "missing_required_evidence",
        "klarman_gates": {
            "matrix": {
                name: {"required": True, "status": "pass" if passed else "missing"}
                for name, passed in gates.items()
            },
            "missing_required": missing,
        },
        "deal_terms": deal_terms,
        "valuation": valuation,
        "downside_case": downside,
        "risk_budget_inputs": {
            "worst_case_loss_pct": permanent_loss,
            "liquidity_bucket": (evidence.get("liquidity") or {}).get("bucket")
            if isinstance(evidence.get("liquidity"), Mapping)
            else None,
            "dependency_tags": list(evidence.get("dependency_tags") or []),
            "diversification_required": evidence.get("situation_type")
            in {"reorganization", "spin_off", "distress_turnaround"},
        },
    }


def apply_underwriting(
    evidence: Mapping[str, Any],
    *,
    situation_type: str | None = None,
    policy: ResearchPolicy | None = None,
    atoms: Iterable[EvidenceAtom | Mapping[str, Any]] | None = None,
    compiled_evidence: Mapping[str, Any] | None = None,
    minimum_margin_of_safety: float | None = None,
    failure_probability_stress: float | None = None,
) -> dict[str, Any]:
    if situation_type is not None or atoms is not None or compiled_evidence is not None or policy is not None:
        selected = _policy_for_legacy(policy, minimum_margin_of_safety, failure_probability_stress)
        return _v7_underwriting(evidence, situation_type=situation_type or str(evidence.get("situation_type") or ""), policy=selected, atoms=atoms, compiled_evidence=compiled_evidence)
    return _legacy_underwriting(evidence, minimum_margin_of_safety=minimum_margin_of_safety, failure_probability_stress=failure_probability_stress)
