#!/usr/bin/env python3
"""Validate an event-risk-alert watchlist JSON file."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SYMBOL_RE = re.compile(r"^(?:\d{6}\.(?:SZ|SH|BJ)|[A-Z0-9._-]+)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEFAULT_RULES = {
    "restricted_unlock_days",
    "high_unlock_float_pct",
    "medium_pledge_total_ratio",
    "high_pledge_total_ratio",
    "holder_count_increase_pct",
}


def fail(message: str) -> int:
    print(f"[invalid] {message}", file=sys.stderr)
    return 1


def validate_rules(rules: Any) -> list[str]:
    errors: list[str] = []
    if rules is None:
        return errors
    if not isinstance(rules, dict):
        return ["rules must be an object when present"]
    for key, value in rules.items():
        if key not in DEFAULT_RULES:
            errors.append(f"rules.{key} is not a recognized override")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"rules.{key} must be numeric")
        elif value < 0:
            errors.append(f"rules.{key} must be non-negative")
    return errors


def validate_symbol_entry(entry: Any, index: int) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    if isinstance(entry, str):
        symbol = entry.strip()
        name = None
        tags = None
    elif isinstance(entry, dict):
        symbol = str(entry.get("symbol", "")).strip()
        name = entry.get("name")
        tags = entry.get("tags")
        if "position_cost" in entry and not isinstance(entry["position_cost"], (int, float)):
            errors.append(f"symbols[{index}].position_cost must be numeric")
    else:
        return None, [f"symbols[{index}] must be a string or object"]

    if not symbol:
        errors.append(f"symbols[{index}].symbol is required")
    elif not SYMBOL_RE.match(symbol):
        errors.append(f"symbols[{index}].symbol has invalid format: {symbol}")

    if name is not None and not isinstance(name, str):
        errors.append(f"symbols[{index}].name must be a string")
    if tags is not None and (
        not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags)
    ):
        errors.append(f"symbols[{index}].tags must be a list of strings")

    return symbol or None, errors


def validate_watchlist(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["watchlist root must be a JSON object"]

    as_of = data.get("as_of")
    if as_of is not None and (not isinstance(as_of, str) or not DATE_RE.match(as_of)):
        errors.append("as_of must use YYYY-MM-DD")

    symbols = data.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        errors.append("symbols must be a non-empty list")
        symbols = []

    seen: set[str] = set()
    for index, entry in enumerate(symbols):
        symbol, entry_errors = validate_symbol_entry(entry, index)
        errors.extend(entry_errors)
        if symbol:
            if symbol in seen:
                errors.append(f"duplicate symbol: {symbol}")
            seen.add(symbol)

    errors.extend(validate_rules(data.get("rules")))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("watchlist", type=Path, help="Path to watchlist.json")
    args = parser.parse_args()

    try:
        data = json.loads(args.watchlist.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fail(f"file not found: {args.watchlist}")
    except json.JSONDecodeError as exc:
        return fail(f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")

    errors = validate_watchlist(data)
    if errors:
        for error in errors:
            print(f"[invalid] {error}", file=sys.stderr)
        return 1

    print(f"[ok] {args.watchlist} contains {len(data['symbols'])} symbol(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
