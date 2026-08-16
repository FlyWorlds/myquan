#!/usr/bin/env python3
"""Extract metrics with structured sources taking precedence only when unambiguous."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

METRIC_NAMES = {"sharpe", "annual_return", "max_drawdown", "ic", "icir", "turnover", "accuracy", "sample_count"}
NUMBER = r"[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?"


def structured(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() != ".json":
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    metrics = value.get("metrics", value) if isinstance(value, dict) else {}
    return [{"name": key, "value": value, "source_file": path.as_posix(), "source_type": "structured", "location": f"metrics.{key}", "status": "confirmed"} for key, value in metrics.items() if key in METRIC_NAMES and isinstance(value, (int, float))]


def text_metrics(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    found = []
    for name in METRIC_NAMES:
        label = name.replace("_", "[ _-]?" )
        match = re.search(rf"(?i)\b{label}\b\s*[:=：]\s*({NUMBER})", text)
        if match:
            found.append({"name": name, "value": float(match.group(1)), "source_file": path.as_posix(), "source_type": "text", "location": f"line:{text[:match.start()].count(chr(10)) + 1}", "status": "extracted_from_text"})
    return found


def extract(root: Path) -> dict[str, Any]:
    candidates = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".json", ".md", ".txt", ".log"}:
            candidates.extend(structured(path))
            if path.suffix.lower() != ".json":
                candidates.extend(text_metrics(path))
    by_name: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        by_name.setdefault(item["name"], []).append(item)
    metrics = []
    for name, items in sorted(by_name.items()):
        values = {str(item["value"]) for item in items}
        if len(values) > 1:
            metrics.append({"name": name, "status": "conflict_unresolved", "candidates": items, "requires_review": True})
        else:
            metrics.append(items[0])
    return {"result_version": 1, "metrics": metrics}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    output = json.dumps(extract(args.root), ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
