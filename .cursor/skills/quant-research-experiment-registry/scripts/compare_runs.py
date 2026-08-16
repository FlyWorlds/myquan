#!/usr/bin/env python3
"""Compare two metric objects using explicitly declared rules."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def compare(left: dict, right: dict, rules: dict) -> dict:
    differences = []
    for name, rule in rules.items():
        if name not in left or name not in right:
            differences.append({"name": name, "status": "missing"})
            continue
        a, b = left[name], right[name]
        method = rule.get("method")
        ok = False
        if method == "exact": ok = a == b
        elif method == "absolute_tolerance": ok = math.isclose(a, b, abs_tol=float(rule["tolerance"]), rel_tol=0)
        elif method == "relative_tolerance": ok = math.isclose(a, b, abs_tol=0, rel_tol=float(rule["tolerance"]))
        elif method == "set_equal": ok = set(a) == set(b)
        elif method == "ordered_sequence_equal": ok = list(a) == list(b)
        differences.append({"name": name, "status": "matched" if ok else "different", "original": a, "reproduction": b, "method": method})
    overall = "reproduced" if differences and all(item["status"] == "matched" for item in differences) else "not_reproduced"
    if not rules: overall = "comparison_rule_missing"
    return {"status": overall, "differences": differences}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("original", type=Path)
    parser.add_argument("reproduction", type=Path)
    parser.add_argument("rules", type=Path)
    args = parser.parse_args()
    result = compare(json.loads(args.original.read_text()), json.loads(args.reproduction.read_text()), json.loads(args.rules.read_text()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "reproduced" else 1)


if __name__ == "__main__":
    main()
