#!/usr/bin/env python3
"""Validate common safety properties of a CSV parent or child order file."""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path


VALID_SIDES = {"BUY", "SELL"}
VALID_ORDER_TYPES = {"MARKET", "LIMIT", "STOP", "STOP_LIMIT", "PEG", "ICEBERG"}
VALID_TIFS = {"DAY", "GTC", "IOC", "FOK", "GTX", "GTD"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check order IDs, sides, quantities, prices, time-in-force, and participation."
    )
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--max-participation", type=float)
    parser.add_argument("--max-child-orders-per-parent", type=int)
    return parser.parse_args()


def parse_positive(value: str, label: str, row_number: int, errors: list[str]) -> float | None:
    try:
        number = float(value)
    except ValueError:
        errors.append(f"row {row_number}: invalid {label} {value!r}")
        return None
    if not math.isfinite(number) or number <= 0:
        errors.append(f"row {row_number}: {label} must be finite and positive")
        return None
    return number


def validate(args: argparse.Namespace) -> int:
    if not args.csv_path.exists():
        print(f"ERROR: file not found: {args.csv_path}")
        return 1
    if args.max_participation is not None and (
        not math.isfinite(args.max_participation) or args.max_participation <= 0
    ):
        print("ERROR: --max-participation must be finite and positive")
        return 1
    if args.max_child_orders_per_parent is not None and args.max_child_orders_per_parent < 0:
        print("ERROR: --max-child-orders-per-parent must be nonnegative")
        return 1

    errors: list[str] = []
    order_ids: set[str] = set()
    parent_counts: dict[str, int] = {}
    order_count = 0
    parent_ids: set[str] = set()
    buy_qty = 0.0
    sell_qty = 0.0

    try:
        with args.csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            required = {"order_id", "parent_id", "asset_id", "side", "qty", "order_type"}
            headers = set(reader.fieldnames or [])
            missing = sorted(required - headers)
            if missing:
                print("ERROR: missing columns: " + ", ".join(missing))
                return 1
            if args.max_participation is not None and "adv_qty" not in headers:
                print("ERROR: adv_qty column is required with --max-participation")
                return 1

            for row_number, row in enumerate(reader, start=2):
                order_count += 1
                order_id = (row.get("order_id") or "").strip()
                parent_id = (row.get("parent_id") or "").strip()
                asset_id = (row.get("asset_id") or "").strip()
                side = (row.get("side") or "").strip().upper()
                order_type = (row.get("order_type") or "").strip().upper()
                tif = (row.get("time_in_force") or "").strip().upper() if "time_in_force" in headers else ""

                if not order_id:
                    errors.append(f"row {row_number}: blank order_id")
                elif order_id in order_ids:
                    errors.append(f"row {row_number}: duplicate order_id {order_id!r}")
                order_ids.add(order_id)
                if not parent_id:
                    errors.append(f"row {row_number}: blank parent_id")
                else:
                    parent_ids.add(parent_id)
                    parent_counts[parent_id] = parent_counts.get(parent_id, 0) + 1
                if not asset_id:
                    errors.append(f"row {row_number}: blank asset_id")
                if side not in VALID_SIDES:
                    errors.append(f"row {row_number}: invalid side {side!r}")
                if order_type not in VALID_ORDER_TYPES:
                    errors.append(f"row {row_number}: invalid order_type {order_type!r}")
                if tif and tif not in VALID_TIFS:
                    errors.append(f"row {row_number}: invalid time_in_force {tif!r}")

                qty = parse_positive((row.get("qty") or "").strip(), "qty", row_number, errors)
                if qty is not None:
                    if side == "BUY":
                        buy_qty += qty
                    elif side == "SELL":
                        sell_qty += qty
                    if args.max_participation is not None:
                        adv = parse_positive((row.get("adv_qty") or "").strip(), "adv_qty", row_number, errors)
                        if adv is not None and qty / adv > args.max_participation:
                            errors.append(f"row {row_number}: order participation exceeds limit")

                if order_type in {"LIMIT", "STOP_LIMIT"}:
                    parse_positive((row.get("limit_price") or "").strip(), "limit_price", row_number, errors)
                if order_type in {"STOP", "STOP_LIMIT"}:
                    parse_positive((row.get("stop_price") or "").strip(), "stop_price", row_number, errors)

            if args.max_child_orders_per_parent is not None:
                for parent_id, count in sorted(parent_counts.items()):
                    if count > args.max_child_orders_per_parent:
                        errors.append(f"parent {parent_id!r}: child order count exceeds limit")
    except (OSError, csv.Error) as exc:
        print(f"ERROR: could not read CSV: {exc}")
        return 1

    print(
        f"orders={order_count} parents={len(parent_ids)} "
        f"buy_qty={buy_qty:.10g} sell_qty={sell_qty:.10g}"
    )
    for error in errors:
        print("ERROR: " + error)
    if errors:
        print(f"FAILED: {len(errors)} error(s)")
        return 1
    print("PASSED")
    return 0


def main() -> int:
    return validate(parse_args())


if __name__ == "__main__":
    sys.exit(main())
