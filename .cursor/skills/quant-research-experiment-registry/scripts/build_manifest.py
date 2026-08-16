#!/usr/bin/env python3
"""Build a manifest from prior scanner/normalizer outputs."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fingerprint import fingerprint


def build(scan: dict[str, Any], config: dict[str, Any], results: dict[str, Any] | None = None) -> dict[str, Any]:
    variants = config.get("variants", [])
    variant = variants[0] if variants else {}
    missing = variant.get("missing_core_fields", [])
    sensitive = [item["path"] for item in scan.get("assets", []) if item.get("sensitive")]
    status = "blocked" if missing else "partial"
    checks = {
        "config": {"status": "failed" if missing else "passed", "missing_core_fields": missing},
        "assets": {"status": "passed", "sensitive_excluded": sensitive},
        "data": {"status": "not_checked", "reason": "No live or normalized PandaData snapshot was supplied"},
        "environment": {"status": "not_checked", "reason": "Environment collection is opt-in"},
        "execution": {"status": "not_checked", "reason": "No confirmed command execution"},
        "lookahead_risk": {"status": "not_checked", "reason": "No provider availability metadata or external leakage result supplied"},
        "result_comparison": {"status": "not_checked", "reason": "No reproduction comparison supplied"},
    }
    if results:
        checks["results"] = {"status": "passed", "metrics": results.get("metrics", [])}
    return {
        "manifest_version": "1.0.0", "schema_id": "quant-experiment-manifest", "schema_revision": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "experiment": {"variant_id": variant.get("variant_id", "unknown"), "source_config": variant.get("source_config"), "fingerprint": fingerprint(variant)},
        "configuration": variant,
        "assets": scan.get("assets", []),
        "data_snapshots": [], "checks": checks,
        "reproducibility": {"overall_status": status, "blocking_items": missing, "warnings": ["data_not_checked", "lookahead_not_checked"], "unresolved_items": []},
        "extensions": {"synthetic_fixture": True},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    scan = json.loads(args.scan.read_text(encoding="utf-8"))
    config = json.loads(args.config.read_text(encoding="utf-8"))
    results = json.loads(args.results.read_text(encoding="utf-8")) if args.results else None
    args.out.write_text(json.dumps(build(scan, config, results), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
