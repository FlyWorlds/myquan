#!/usr/bin/env python3
"""Validate manifest core structure without requiring third-party JSON schema packages."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

STATUSES = {"verified", "partial", "blocked", "failed"}
REQUIRED = {"manifest_version", "schema_id", "schema_revision", "experiment", "configuration", "assets", "data_snapshots", "checks", "reproducibility", "extensions"}


def validate(value: dict) -> list[str]:
    errors = []
    errors.extend(f"missing:{key}" for key in sorted(REQUIRED - value.keys()))
    if value.get("schema_id") != "quant-experiment-manifest": errors.append("schema_id")
    if not isinstance(value.get("schema_revision"), int): errors.append("schema_revision")
    repro = value.get("reproducibility", {})
    if repro.get("overall_status") not in STATUSES: errors.append("reproducibility.overall_status")
    if not isinstance(value.get("assets"), list): errors.append("assets")
    if not isinstance(value.get("data_snapshots"), list): errors.append("data_snapshots")
    if not isinstance(value.get("checks"), dict): errors.append("checks")
    if not isinstance(value.get("extensions"), dict): errors.append("extensions")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        value = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid JSON: {exc}")
    if not isinstance(value, dict): raise SystemExit("manifest root must be an object")
    errors = validate(value)
    if errors:
        for error in errors: print(f"ERROR {error}")
        raise SystemExit(1)
    print("manifest validation passed")


if __name__ == "__main__":
    main()
