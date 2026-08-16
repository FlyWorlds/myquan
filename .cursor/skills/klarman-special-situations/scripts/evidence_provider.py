"""Pluggable V7 evidence providers; JSON is the public portable format."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

import pandas as pd

try:
    from .evidence_model import EvidenceAtom, compile_evidence
except ImportError:  # pragma: no cover - direct script execution
    from evidence_model import EvidenceAtom, compile_evidence


class EvidenceProvider(Protocol):
    def load(self, *, as_of_date: str) -> list[dict[str, Any]]: ...


class JsonEvidenceProvider:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def load(self, *, as_of_date: str) -> list[dict[str, Any]]:
        if not self.directory.is_dir():
            raise ValueError(f"evidence_dir 不存在: {self.directory}")
        bundles: list[dict[str, Any]] = []
        for path in sorted(self.directory.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            rows = raw.get("events") if isinstance(raw, Mapping) else raw
            if not isinstance(rows, list):
                raise ValueError(f"证据文件必须是事件数组: {path.name}")
            for item in rows:
                if not isinstance(item, Mapping):
                    raise ValueError(f"证据事件必须是映射: {path.name}")
                bundle = dict(item)
                bundle["_bundle_path"] = str(path)
                bundles.append(bundle)
        return bundles


def provider_from_config(config: Mapping[str, Any]) -> EvidenceProvider | None:
    provider = config.get("evidence_provider")
    if provider is not None:
        if not hasattr(provider, "load"):
            raise ValueError("evidence_provider 必须提供 load(as_of_date=...)")
        return provider
    directory = config.get("evidence_dir")
    return JsonEvidenceProvider(directory) if directory else None


def bundle_matches(bundle: Mapping[str, Any], payload: Mapping[str, Any], target_id: str) -> bool:
    event_id = str(bundle.get("event_id") or bundle.get("event_family_id") or "")
    if event_id and event_id == str(target_id):
        return True
    return (
        bool(bundle.get("symbol"))
        and str(bundle.get("symbol")) == str(payload.get("symbol"))
        and str(bundle.get("situation_type"))
        in {str(payload.get("situation_type")), "distress" if payload.get("situation_type") == "distress_turnaround" else ""}
    )


def _risk_atom(symbol: str, api_name: str, frame: pd.DataFrame, as_of_date: str) -> EvidenceAtom:
    subset = frame
    if not frame.empty and "symbol" in frame:
        subset = frame.loc[frame["symbol"].astype(str).str.replace(".SS", ".SH", regex=False) == symbol]
    record = {"api": api_name, "symbol": symbol, "row_count": len(subset)}
    content = json.dumps(record, sort_keys=True, ensure_ascii=True)
    return EvidenceAtom.from_mapping(
        {
            "atom_id": f"panda-risk-{api_name}-{symbol}",
            "field_name": f"risk.{api_name}.row_count",
            "value": len(subset),
            "unit": "rows",
            "currency": None,
            "basis": "reported",
            "source_type": "panda_api",
            "source_ref": api_name,
            "source_record_id": f"{api_name}:{symbol}:{as_of_date}",
            "available_date": as_of_date,
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "extraction_method": "provider",
            "evidence_kind": "structured_fact",
            "core": False,
        }
    )


def panda_risk_atoms(
    symbol: str, risk_frames: Mapping[str, pd.DataFrame], as_of_date: str
) -> list[EvidenceAtom]:
    return [_risk_atom(symbol, name, frame, as_of_date) for name, frame in risk_frames.items()]


def bundle_evidence(bundle: Mapping[str, Any], *, as_of_date: str) -> tuple[dict[str, Any], dict[str, Any]]:
    facts = dict(bundle.get("facts") or {})
    for key in ("symbol", "situation_type"):
        if key in bundle and key not in facts:
            facts[key] = bundle[key]
    raw_atoms = bundle.get("atoms") or []
    if not isinstance(raw_atoms, Iterable) or isinstance(raw_atoms, (str, bytes, Mapping)):
        raise ValueError("bundle atoms 必须是数组")
    atoms = [item if isinstance(item, EvidenceAtom) else EvidenceAtom.from_mapping(item) for item in raw_atoms]
    return facts, compile_evidence(atoms, as_of_date=as_of_date)
