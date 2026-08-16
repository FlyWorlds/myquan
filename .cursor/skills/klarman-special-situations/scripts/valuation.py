"""Deterministic, provenance-checked valuation formulas for V7."""

from __future__ import annotations

from typing import Any, Mapping, Iterable

try:
    from .evidence_model import EvidenceAtom, atom_mapping
    from .policy import ResearchPolicy
except ImportError:  # pragma: no cover - direct script execution
    from evidence_model import EvidenceAtom, atom_mapping
    from policy import ResearchPolicy


def _number(facts: Mapping[str, Any], name: str) -> float:
    value = facts.get(name)
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if number != number:
        raise ValueError(f"{name} must be finite")
    return number


def _lineage(facts: Mapping[str, Any], atoms: Iterable[EvidenceAtom], names: list[str]) -> list[str]:
    indexed = atom_mapping(atoms)
    ids: list[str] = []
    for name in names:
        if name not in facts:
            raise ValueError(f"missing fact: {name}")
        row = indexed.get(name)
        if row is None or not row.core:
            raise ValueError(f"missing admissible atom: {name}")
        ids.append(row.atom_id)
    return ids


def value_reorganization(
    facts: Mapping[str, Any], atoms: Iterable[EvidenceAtom], policy: ResearchPolicy
) -> dict[str, Any]:
    names = [
        "cash_consideration_per_share",
        "share_exchange_ratio",
        "acquirer_price",
        "consideration_adjustments_per_share",
        "standalone_value_per_share",
        "unaffected_price_per_share",
    ]
    ids = _lineage(facts, atoms, names)
    success = (
        _number(facts, "cash_consideration_per_share")
        + _number(facts, "share_exchange_ratio") * _number(facts, "acquirer_price")
        + _number(facts, "consideration_adjustments_per_share")
    )
    failure = min(
        _number(facts, "standalone_value_per_share"),
        _number(facts, "unaffected_price_per_share"),
    )
    conservative = (1 - policy.failure_probability_stress) * success + policy.failure_probability_stress * failure
    return {
        "success_value": success,
        "failure_value": failure,
        "conservative_value": conservative,
        "formula_id": "reorg_stress_value_v1",
        "input_atom_ids": ids,
        "policy_id": policy.policy_id,
    }


def value_spin_off(
    facts: Mapping[str, Any], atoms: Iterable[EvidenceAtom], policy: ResearchPolicy
) -> dict[str, Any]:
    names = [
        "ownership_pct",
        "subsidiary_value",
        "remaining_business_value",
        "net_debt",
        "tax_leakage",
        "holdco_discount_pct",
        "fully_diluted_shares",
        "failure_value_per_share",
    ]
    ids = _lineage(facts, atoms, names)
    equity = max(
        0.0,
        (
            _number(facts, "ownership_pct") * _number(facts, "subsidiary_value")
            + _number(facts, "remaining_business_value")
            - _number(facts, "net_debt")
            - _number(facts, "tax_leakage")
        )
        * (1 - _number(facts, "holdco_discount_pct")),
    )
    conservative = equity / _number(facts, "fully_diluted_shares")
    return {
        "success_value": conservative,
        "failure_value": _number(facts, "failure_value_per_share"),
        "conservative_value": conservative,
        "formula_id": "spin_off_sotp_v1",
        "input_atom_ids": ids,
        "policy_id": policy.policy_id,
    }


def value_distress(
    facts: Mapping[str, Any], atoms: Iterable[EvidenceAtom], policy: ResearchPolicy
) -> dict[str, Any]:
    categories = facts.get("asset_recovery_values")
    if not isinstance(categories, Mapping) or not categories:
        raise ValueError("asset_recovery_values must be a non-empty mapping")
    names = [f"asset_recovery_values.{key}" for key in categories]
    names.extend(
        [
            "secured_debt",
            "priority_claims",
            "unsecured_debt",
            "contingent_liabilities",
            "restructuring_costs",
            "fully_diluted_shares",
        ]
    )
    ids = _lineage(
        {**facts, **{f"asset_recovery_values.{key}": value for key, value in categories.items()}},
        atoms,
        names,
    )
    residual = max(
        0.0,
        sum(float(value) for value in categories.values())
        - _number(facts, "secured_debt")
        - _number(facts, "priority_claims")
        - _number(facts, "unsecured_debt")
        - _number(facts, "contingent_liabilities")
        - _number(facts, "restructuring_costs"),
    )
    conservative = residual / _number(facts, "fully_diluted_shares")
    return {
        "success_value": conservative,
        "failure_value": 0.0,
        "conservative_value": conservative,
        "formula_id": "distress_equity_waterfall_v1",
        "input_atom_ids": ids,
        "policy_id": policy.policy_id,
    }
