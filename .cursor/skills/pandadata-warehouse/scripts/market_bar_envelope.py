"""Strict Pandadata native-bar to QuantSkills market-bar converter."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re


class ContractError(ValueError):
    """Raised when native input cannot be represented losslessly."""


_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
_MAX_SAFE_INTEGER = 2**53 - 1
_FREQUENCIES = {"1m", "5m", "1h", "1d", "1w", "1mo"}
_VOLUME_UNITS = {"shares", "contracts", "lots", "units", "currency"}
_ADJUSTMENTS = {"none", "split", "total-return"}


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _json_value(value: object, active: set[int] | None = None) -> None:
    active = set() if active is None else active
    if type(value) is dict:
        if id(value) in active or any(type(key) is not str for key in value):
            raise ContractError("native JSON must be acyclic objects with string keys")
        active.add(id(value))
        try:
            for item in value.values():
                _json_value(item, active)
        finally:
            active.remove(id(value))
    elif type(value) is list:
        if id(value) in active:
            raise ContractError("native JSON must be acyclic")
        active.add(id(value))
        try:
            for item in value:
                _json_value(item, active)
        finally:
            active.remove(id(value))
    elif type(value) is int:
        if abs(value) > _MAX_SAFE_INTEGER:
            raise ContractError("native integer exceeds JSON safe range")
    elif type(value) is float:
        if not math.isfinite(value):
            raise ContractError("native values must be finite")
    elif type(value) not in (str, bool, type(None)):
        raise ContractError("native value is not JSON shaped")


def _text(value: object) -> bool:
    return type(value) is str and bool(value)


def _datetime(value: object) -> bool:
    if not _text(value) or _DATETIME.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return True


def _number(value: object, nonnegative: bool = False) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and (not nonnegative or value >= 0)


def _validate(native: object) -> tuple[dict, list[dict]]:
    if type(native) is not dict:
        raise ContractError("native input must be an object")
    _json_value(native)
    metadata, rows = native.get("metadata"), native.get("records")
    if (
        not all(_text(native.get(key)) for key in ("provider", "dataset", "raw_ref"))
        or not _datetime(native.get("generated_at"))
        or type(metadata) is not dict
        or type(rows) is not list
        or not rows
        or any(type(row) is not dict for row in rows)
        or not all(_text(metadata.get(key)) for key in ("producer", "timezone", "calendar"))
        or not re.fullmatch(r"[A-Z]{3}", metadata.get("currency", ""))
        or metadata.get("frequency") not in _FREQUENCIES
    ):
        raise ContractError("native Pandadata market-bar shape is invalid")
    units = set()
    for row in rows:
        valid = (
            all(_text(row.get(key)) for key in ("instrument", "source_timestamp", "adjustment", "volume_unit"))
            and _datetime(row.get("source_timestamp"))
            and row["adjustment"] in _ADJUSTMENTS
            and row["volume_unit"] in _VOLUME_UNITS
            and all(_number(row.get(key)) for key in ("open", "high", "low", "close"))
            and _number(row.get("volume"), nonnegative=True)
        )
        if not valid or row["low"] > row["high"] or not row["low"] <= row["open"] <= row["high"] or not row["low"] <= row["close"] <= row["high"]:
            raise ContractError("native Pandadata OHLCV record is invalid")
        units.add(row["volume_unit"])
    if len(units) != 1:
        raise ContractError("mixed volume units cannot be represented losslessly")
    return metadata, rows


def to_envelope(native: object) -> dict:
    """Convert validated provider-native JSON without changing source values."""
    metadata, rows = _validate(native)
    volume_unit = rows[0]["volume_unit"]
    fields = {
        "instrument_id": {"type": "string", "nullable": False},
        "timestamp": {"type": "string", "nullable": False, "format": "date-time"},
        "open": {"type": "number", "nullable": False, "unit": "currency"},
        "high": {"type": "number", "nullable": False, "unit": "currency"},
        "low": {"type": "number", "nullable": False, "unit": "currency"},
        "close": {"type": "number", "nullable": False, "unit": "currency"},
        "volume": {"type": "number", "nullable": False, "unit": volume_unit},
        "frequency": {"type": "string", "nullable": False},
        "adjustment": {"type": "string", "nullable": False},
        "calendar": {"type": "string", "nullable": False},
    }
    records = [
        {"instrument_id": row["instrument"], "timestamp": row["source_timestamp"], "open": row["open"], "high": row["high"], "low": row["low"], "close": row["close"], "volume": row["volume"], "frequency": metadata["frequency"], "adjustment": row["adjustment"], "calendar": metadata["calendar"]}
        for row in rows
    ]
    return {
        "$contract": {"envelope": "quantskills-envelope", "envelope_version": "1.0.0", "profile": "market-bar", "profile_version": "1.0.0"},
        "meta": {"dataset_id": native["dataset"], "producer": metadata["producer"], "generated_at": native["generated_at"], "timezone": metadata["timezone"], "currency": metadata["currency"], "calendar": metadata["calendar"], "provenance": [{"provider": native["provider"], "dataset": native["dataset"], "raw_ref": native["raw_ref"], "raw_sha256": "sha256:" + hashlib.sha256(_canonical_bytes(native)).hexdigest()}]},
        "schema": {"primary_key": ["instrument_id", "timestamp"], "fields": fields},
        "payload": {"native": {"provider": native["provider"], "raw_ref": native["raw_ref"], "raw_records": [copy.deepcopy(native)]}, "records": copy.deepcopy(records)},
        "quality": {"status": "pass", "checks": ["lossless-native-recovery", "pandadata-market-bar-v1"], "warnings": []},
    }


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ContractError(f"non-standard JSON constant: {value}")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read native JSON: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a market-bar@1.0.0 Envelope from Pandadata native JSON.")
    parser.add_argument("--input", required=True, type=Path, help="provider-native Pandadata JSON")
    parser.add_argument("--output", required=True, type=Path, help="destination Envelope JSON")
    args = parser.parse_args()
    try:
        envelope = to_envelope(_load_json(args.input))
        args.output.write_text(json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    except ContractError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
