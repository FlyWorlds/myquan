"""Replay a Production Shadow mismatch record against Legacy vs Unified.

Read-only. Does not enable USE_UNIFIED_EXIT_ENGINE or SHADOW_UNIFIED_EXIT_ENGINE.
Does not write a ledger, mutate positions, or call AKQUANT.

  python backtest/exit_decision_replay/replay_mismatch.py path.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HOLDING = ROOT / "holdingStocks"
for path in (ROOT, HOLDING):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from holdingStocks.index import _paper_exit_decision_legacy  # noqa: E402
from strategy.exit_rules import shadow as shadow_mod  # noqa: E402
from strategy.exit_rules.shadow import (  # noqa: E402
    build_exit_context_from_paper_kwargs,
    compare_paper_vs_exit,
    paper_kwargs_from_record,
    run_unified_exit,
)

REQUIRED_KEYS = (
    "timestamp",
    "symbol",
    "legacy_action",
    "unified_action",
    "legacy_price",
    "unified_price",
    "legacy_quantity",
    "unified_quantity",
    "legacy_reason_code",
    "unified_reason_code",
    "context_snapshot",
    "position_snapshot",
    "working_stop",
    "open_protect",
    "path",
    "decision_trace",
    "config_version",
)


def _load_records(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    if isinstance(raw, dict) and isinstance(raw.get("records"), list):
        return [row for row in raw["records"] if isinstance(row, dict)]
    if isinstance(raw, dict):
        return [raw]
    raise ValueError(f"unsupported mismatch JSON: {path}")


def _original_mismatch(record: dict[str, Any]) -> bool:
    if "match_action" in record:
        return not (
            bool(record.get("match_action"))
            and bool(record.get("match_price", True))
            and bool(record.get("match_qty", True))
            and bool(record.get("match_reason", True))
        )
    return (
        record.get("legacy_action") != record.get("unified_action", record.get("new_action"))
        or record.get("legacy_reason_code")
        != record.get("unified_reason_code", record.get("unified_rule"))
    )


def replay_mismatch_record(record: dict[str, Any]) -> dict[str, Any]:
    """Re-run Legacy and Unified from the saved snapshot. Never switches production flags."""
    kwargs = paper_kwargs_from_record(record)
    legacy_kw = {k: v for k, v in kwargs.items() if k != "symbol"}
    legacy = _paper_exit_decision_legacy(**legacy_kw)
    ctx = build_exit_context_from_paper_kwargs(**kwargs)
    dec, _adapted = run_unified_exit(ctx)
    compared = compare_paper_vs_exit(legacy, dec, ctx)
    live_exact = bool(
        compared.match_action
        and compared.match_price
        and compared.match_qty
        and compared.match_reason
    )
    live_mismatch = not live_exact
    original_mismatch = _original_mismatch(record)
    recorded_unified = record.get("unified_action") or record.get("new_action")
    recorded_unified_reason = record.get("unified_reason_code") or record.get("unified_rule")
    same_shape = (
        compared.legacy_action == record.get("legacy_action")
        and compared.new_action == recorded_unified
        and str(compared.legacy_rule or "") == str(record.get("legacy_reason_code") or compared.legacy_rule or "")
        and str(compared.unified_rule or "") == str(recorded_unified_reason or compared.unified_rule or "")
    )
    return {
        "symbol": kwargs.get("symbol") or record.get("symbol") or "",
        "timestamp": record.get("timestamp"),
        "exact_match": live_exact,
        "live_mismatch": live_mismatch,
        "original_mismatch": original_mismatch,
        "reproduced": bool(original_mismatch and live_mismatch and same_shape),
        "legacy_action": compared.legacy_action,
        "unified_action": compared.new_action,
        "legacy_price": compared.legacy_price,
        "unified_price": compared.new_price,
        "legacy_quantity": compared.quantity_ratio_legacy,
        "unified_quantity": compared.quantity_ratio_new,
        "legacy_reason_code": compared.legacy_rule,
        "unified_reason_code": compared.unified_rule,
        "decision_trace": list(compared.decision_trace or ()),
        "paper_kwargs": kwargs,
        "config_version": record.get("config_version") or compared.config_version,
        "USE_UNIFIED_EXIT_ENGINE": bool(shadow_mod.USE_UNIFIED_EXIT_ENGINE),
        "SHADOW_UNIFIED_EXIT_ENGINE": bool(shadow_mod.SHADOW_UNIFIED_EXIT_ENGINE),
    }


def replay_file(path: Path) -> dict[str, Any]:
    rows = [replay_mismatch_record(rec) for rec in _load_records(path)]
    return {
        "input": str(path),
        "n": len(rows),
        "reproduced": sum(1 for r in rows if r["reproduced"]),
        "live_mismatch": sum(1 for r in rows if r["live_mismatch"]),
        "exact_match": sum(1 for r in rows if r["exact_match"]),
        "records": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay a Shadow mismatch record (Legacy vs Unified)")
    parser.add_argument("path", type=Path, help="JSON mismatch record (object or list)")
    parser.add_argument("--out", type=Path, default=None, help="optional JSON output (tool-side, not paper)")
    args = parser.parse_args(argv)
    summary = replay_file(args.path)
    text = json.dumps(
        {k: v for k, v in summary.items() if k != "records"}
        | {"records": summary["records"]},
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")
    return 0 if summary["live_mismatch"] == 0 or summary["reproduced"] == summary["live_mismatch"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
