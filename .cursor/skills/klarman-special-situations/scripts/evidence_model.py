"""Provenance-first evidence atoms and point-in-time compilation."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
import re
from typing import Any, Iterable, Mapping


ALLOWED_SOURCE_TYPES = {
    "panda_api",
    "exchange_filing",
    "csrc_filing",
    "company_filing",
    "court_announcement",
    "exchange_disclosure",
    "court_docket",
    "audit_report",
}
CORE_EVIDENCE_KINDS = {"structured_fact"}
CORE_EXTRACTION_METHODS = {"provider"}
_DATE_RE = re.compile(r"^\d{8}$")
_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _required_text(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class EvidenceAtom:
    atom_id: str
    field_name: str
    value: Any
    unit: str | None
    currency: str | None
    basis: str
    source_type: str
    source_ref: str
    source_record_id: str
    available_date: str
    content_hash: str
    extraction_method: str
    evidence_kind: str
    core: bool

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "EvidenceAtom":
        if not isinstance(data, Mapping):
            raise ValueError("EvidenceAtom must be a mapping")
        atom_id = _required_text(data, "atom_id")
        field_name = _required_text(data, "field_name")
        basis = _required_text(data, "basis")
        source_type = _required_text(data, "source_type")
        source_ref = _required_text(data, "source_ref")
        record_id = _required_text(data, "source_record_id")
        available_date = _required_text(data, "available_date")
        if not _DATE_RE.match(available_date):
            raise ValueError("available_date must use YYYYMMDD")
        try:
            datetime.strptime(available_date, "%Y%m%d")
        except ValueError as exc:
            raise ValueError("available_date must be a real date") from exc
        content_hash = _required_text(data, "content_hash")
        if not _HASH_RE.match(content_hash):
            raise ValueError("content_hash must be a 64-character hex digest")
        extraction_method = _required_text(data, "extraction_method")
        evidence_kind = _required_text(data, "evidence_kind")
        core = data.get("core")
        if not isinstance(core, bool):
            raise ValueError("core must be boolean")
        if source_type not in ALLOWED_SOURCE_TYPES:
            raise ValueError(f"source_type not allowlisted: {source_type}")
        if evidence_kind not in {"structured_fact", "narrative"}:
            raise ValueError("evidence_kind must be structured_fact or narrative")
        if extraction_method not in {"provider", "manual"}:
            raise ValueError("extraction_method must be provider or manual")
        if core and (evidence_kind not in CORE_EVIDENCE_KINDS or extraction_method not in CORE_EXTRACTION_METHODS):
            raise ValueError("core evidence must be provider-backed structured_fact")
        if "value" not in data:
            raise ValueError("value is required")
        if "unit" not in data:
            raise ValueError("unit is required")
        if "currency" not in data:
            raise ValueError("currency is required")
        return cls(
            atom_id=atom_id,
            field_name=field_name,
            value=data["value"],
            unit=data["unit"],
            currency=data["currency"],
            basis=basis,
            source_type=source_type,
            source_ref=source_ref,
            source_record_id=record_id,
            available_date=available_date,
            content_hash=content_hash.lower(),
            extraction_method=extraction_method,
            evidence_kind=evidence_kind,
            core=core,
        )


@dataclass(frozen=True)
class DerivedMetric:
    metric_id: str
    metric_name: str
    formula_id: str
    input_atom_ids: tuple[str, ...]
    value: float
    unit: str
    currency: str | None
    basis: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DerivedMetric":
        if not isinstance(data, Mapping):
            raise ValueError("DerivedMetric must be a mapping")
        for key in ("metric_id", "metric_name", "formula_id", "unit", "basis"):
            _required_text(data, key)
        if "input_atom_ids" not in data:
            raise ValueError("input_atom_ids is required")
        input_ids = data["input_atom_ids"]
        if not isinstance(input_ids, (list, tuple)) or not input_ids:
            raise ValueError("input_atom_ids must be non-empty")
        if any(not isinstance(item, str) or not item.strip() for item in input_ids):
            raise ValueError("input_atom_ids must contain non-empty strings")
        if len(set(input_ids)) != len(input_ids):
            raise ValueError("input_atom_ids must be unique")
        if "value" not in data:
            raise ValueError("value is required")
        try:
            value = float(data["value"])
        except (TypeError, ValueError) as exc:
            raise ValueError("value must be numeric") from exc
        if "currency" not in data:
            raise ValueError("currency is required")
        return cls(
            metric_id=str(data["metric_id"]).strip(),
            metric_name=str(data["metric_name"]).strip(),
            formula_id=str(data["formula_id"]).strip(),
            input_atom_ids=tuple(input_ids),
            value=value,
            unit=str(data["unit"]).strip(),
            currency=data["currency"],
            basis=str(data["basis"]).strip(),
        )


def _coerce_atoms(atoms: Iterable[EvidenceAtom | Mapping[str, Any]]) -> list[EvidenceAtom]:
    return [item if isinstance(item, EvidenceAtom) else EvidenceAtom.from_mapping(item) for item in atoms]


def knowledge_cutoff_from_atoms(
    atoms: Iterable[EvidenceAtom | Mapping[str, Any]], as_of_date: str | None = None
) -> str | None:
    rows = _coerce_atoms(atoms)
    if as_of_date is not None:
        rows = [row for row in rows if row.available_date <= str(as_of_date)]
    return max((row.available_date for row in rows), default=None)


def compile_evidence(
    atoms: Iterable[EvidenceAtom | Mapping[str, Any]], *, as_of_date: str | None = None
) -> dict[str, Any]:
    rows = _coerce_atoms(atoms)
    usable: list[EvidenceAtom] = []
    excluded: list[dict[str, str]] = []
    for row in rows:
        if as_of_date is not None and row.available_date > str(as_of_date):
            excluded.append({"atom_id": row.atom_id, "reason": "future_evidence"})
            continue
        usable.append(row)
    usable.sort(key=lambda item: (item.available_date, item.atom_id))
    manifest = {
        "atom_count": len(usable),
        "atom_ids": [item.atom_id for item in usable],
        "source_records": [item.source_record_id for item in usable],
        "content_hashes": [item.content_hash for item in usable],
    }
    return {
        "atoms": usable,
        "excluded_atoms": excluded,
        "knowledge_cutoff": knowledge_cutoff_from_atoms(usable),
        "evidence_manifest": manifest,
    }


def atom_mapping(atoms: Iterable[EvidenceAtom | Mapping[str, Any]]) -> dict[str, EvidenceAtom]:
    rows = _coerce_atoms(atoms)
    return {row.field_name: row for row in rows}


def atom_dict(atom: EvidenceAtom) -> dict[str, Any]:
    return asdict(atom)
