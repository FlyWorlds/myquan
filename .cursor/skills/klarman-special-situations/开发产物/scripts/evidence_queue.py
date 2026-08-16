"""P2 evidence-completion queue; invalid bundles never enter underwriting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

try:
    from .evidence_provider import bundle_evidence
except ImportError:
    from evidence_provider import bundle_evidence


GATE_ATOM_ALIASES = {
    "reorganization": {
        "catalyst": {"catalyst_verified", "regulatory_catalyst"},
        "deal_terms": {"consideration", "conditions_verified", "termination_terms_verified"},
        "conservative_value": {"success_value_per_share", "conservative_value"},
        "failure_value": {"break_value_per_share", "failure_value"},
        "capital_structure": {"capital_structure_verified"},
        "legal_accounting": {"legal_accounting_verified", "audit_opinion"},
        "liquidity": {"liquidity_verified", "market_price"},
    },
    "spin_off": {
        "catalyst": {"spinoff_announced", "catalyst_verified"},
        "deal_terms": {"parent_holding_ratio", "ownership_pct"},
        "conservative_value": {"subsidiary_conservative_value", "subsidiary_value"},
        "failure_value": {"failure_value_per_share"},
        "capital_structure": {"net_debt", "fully_diluted_shares"},
        "legal_accounting": {"legal_accounting_verified", "audit_opinion"},
        "liquidity": {"liquidity_verified", "market_price"},
    },
    "distress": {
        "catalyst": {"court_restructuring_status", "st_designation", "catalyst_verified"},
        "conservative_value": {"recoverable_assets", "asset_recovery_values"},
        "failure_value": {"failure_value_per_share", "liquidation_value"},
        "capital_structure": {"secured_debt", "priority_claims", "fully_diluted_shares"},
        "legal_accounting": {"audit_opinion", "legal_accounting_verified"},
        "liquidity": {"liquidity_verified", "market_price"},
    },
}
GATE_ATOM_ALIASES["distress_turnaround"] = GATE_ATOM_ALIASES["distress"]
RISK_WATCH_ATOMS = {"issue_price", "unlock_date"}


def _error_code(exc: Exception) -> str:
    message = str(exc).lower()
    if "sha-256" in message or "content_hash" in message or "64-character hex" in message:
        return "invalid_content_hash"
    if "available_date" in message or "yyyymmdd" in message:
        return "invalid_available_date"
    if "source_type" in message:
        return "invalid_source_type"
    if "must be" in message or "必须" in message:
        return "invalid_schema"
    return "bundle_validation_failed"


def review_directory(
    directory: str | Path, *, as_of_date: str, output_path: str | Path | None = None
) -> dict[str, Any]:
    root = Path(directory)
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            bundles = raw.get("events") if isinstance(raw, Mapping) and "events" in raw else raw
            if isinstance(bundles, Mapping):
                bundles = [bundles]
            if not isinstance(bundles, list):
                raise ValueError("事件文件必须是数组或含 events 数组")
            for bundle in bundles:
                facts, compiled = bundle_evidence(bundle, as_of_date=as_of_date)
                situation = str(facts.get("situation_type") or bundle.get("situation_type") or "")
                atom_fields = {atom.field_name for atom in compiled["atoms"] if atom.core}
                if situation == "private_placement_unlock":
                    missing = sorted(RISK_WATCH_ATOMS - atom_fields)
                    status = "ready_for_risk_watch" if not missing else "evidence_incomplete"
                else:
                    gate_aliases = GATE_ATOM_ALIASES.get(situation)
                    if gate_aliases is None:
                        raise ValueError("unsupported situation_type")
                    missing = sorted(
                        gate for gate, aliases in gate_aliases.items() if not (aliases & atom_fields)
                    )
                    status = "ready_for_underwriting" if not missing else "evidence_incomplete"
                rows.append({
                    "file": path.name,
                    "event_family_id": bundle.get("event_family_id"),
                    "revision_id": bundle.get("revision_id"),
                    "symbol": facts.get("symbol") or bundle.get("symbol"),
                    "situation_type": situation,
                    "status": status,
                    "missing_core_gates": missing,
                    "knowledge_cutoff": compiled.get("knowledge_cutoff"),
                })
        except Exception as exc:
            rows.append({"file": path.name, "status": "invalid_bundle", "error_type": type(exc).__name__, "reason": _error_code(exc)})
    report = {
        "as_of_date": as_of_date,
        "bundle_count": len(rows),
        "ready_count": sum(row["status"] == "ready_for_underwriting" for row in rows),
        "rows": rows,
    }
    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)
    return report
