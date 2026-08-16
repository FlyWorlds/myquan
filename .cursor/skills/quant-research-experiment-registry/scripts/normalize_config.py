#!/usr/bin/env python3
"""Normalize experiment configuration into a stable internal contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

CORE_FIELDS = ("data_source", "experiment_period", "features", "label", "time_split", "run_command", "comparison_rules")


def load(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix == ".json":
        return json.loads(text)
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:
            raise SystemExit("YAML requires PyYAML: python -m pip install pyyaml") from exc
        value = yaml.safe_load(text)
        return value or {}
    if suffix == ".toml":
        import tomllib
        return tomllib.loads(text)
    raise SystemExit(f"Unsupported configuration format: {path.suffix}")


def normalize_queries(config: dict[str, Any], base: Path) -> list[dict[str, Any]]:
    source = config.get("panda_data", {}) or {}
    queries = []
    if "method" in source:
        queries.append({"id": source.get("id", "query_001"), "method": source["method"], "params": source.get("params", {}), "fields": source.get("fields", []), "source": "config"})
    for index, item in enumerate(source.get("queries", []) or [], 1):
        queries.append({"id": item.get("id", f"query_{index:03d}"), "method": item.get("method"), "params": item.get("params", {}), "fields": item.get("fields", []), "source": "config"})
    for index, name in enumerate(source.get("query_files", []) or [], len(queries) + 1):
        query_path = (base / name).resolve()
        child = load(query_path)
        queries.extend(normalize_queries({"panda_data": child.get("panda_data", child)}, query_path.parent))
    return queries


def normalize(path: Path) -> dict[str, Any]:
    raw = load(path)
    variants = raw.get("variants") or [{"id": raw.get("variant_id", "default"), "config": raw}]
    normalized = []
    for index, variant in enumerate(variants, 1):
        body = dict(raw)
        body.pop("variants", None)
        body.update(variant.get("config", variant))
        body.pop("id", None)
        missing = [field for field in CORE_FIELDS if field not in body or body[field] in (None, "", [])]
        normalized.append({
            "variant_id": variant.get("id", f"variant_{index:03d}"),
            "source_config": str(path.resolve()),
            "data_source": body.get("data_source", "panda_data"),
            "experiment_period": body.get("experiment_period", {}),
            "hypothesis": body.get("hypothesis"),
            "features": body.get("features"),
            "label": body.get("label"),
            "time_split": body.get("time_split"),
            "random_seed": body.get("random_seed"),
            "run_command": body.get("run_command"),
            "comparison_rules": body.get("comparison_rules", {}),
            "dependencies": body.get("dependencies", []),
            "queries": normalize_queries(body, path.parent),
            "missing_core_fields": missing,
            "status": "complete" if not missing else "incomplete",
            "extensions": body.get("extensions", {}),
        })
    return {"config_version": 1, "source": str(path.resolve()), "variants": normalized}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    output = json.dumps(normalize(args.config), ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
