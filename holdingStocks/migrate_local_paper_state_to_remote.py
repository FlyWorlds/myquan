#!/usr/bin/env python3
"""Migrate local paper state (Windows holdings.json) → remote PaperStatePort.

READ-ONLY by default (dry-run). Only ``--apply`` writes to remote adapter.

Usage:
  python migrate_local_paper_state_to_remote.py
  python migrate_local_paper_state_to_remote.py --root holdingStocks
  python migrate_local_paper_state_to_remote.py --backend memory
  python migrate_local_paper_state_to_remote.py --backend postgres --apply   # R2+

R1: do NOT run --apply against production Postgres.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from paper_state.local_json import (  # noqa: E402
    holdings_to_full_state,
    state_content_hash,
)
from paper_state.port import create_paper_state_port  # noqa: E402


def _load_local(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    holdings_path = root / "holdings.json"
    trades_path = root / "trades.jsonl"
    if not holdings_path.is_file():
        raise FileNotFoundError(f"missing {holdings_path}")
    holdings = json.loads(holdings_path.read_text(encoding="utf-8"))
    trades_rows: list[dict[str, Any]] = []
    if trades_path.is_file():
        for line in trades_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                trades_rows.append(rec)
    return holdings, trades_rows


def _verify(local, remote) -> dict[str, Any]:
    loc_pos = {p.symbol: p for p in local.open_positions()}
    rem_pos = {p.symbol: p for p in remote.open_positions()}
    checks: list[tuple[str, bool, str]] = []

    def ok(name: str, cond: bool, detail: str = "") -> None:
        checks.append((name, cond, detail))

    ok("position_count", len(loc_pos) == len(rem_pos), f"{len(loc_pos)} vs {len(rem_pos)}")
    ok("position_symbols", set(loc_pos) == set(rem_pos), "")
    for sym in sorted(set(loc_pos) | set(rem_pos)):
        lp, rp = loc_pos.get(sym), rem_pos.get(sym)
        if lp is None or rp is None:
            ok(f"pos_{sym}_present", False, "missing side")
            continue
        ok(f"pos_{sym}_qty", int(lp.qty) == int(rp.qty), f"{lp.qty} vs {rp.qty}")
        ok(
            f"pos_{sym}_cost",
            _num_eq(lp.cost, rp.cost),
            f"{lp.cost} vs {rp.cost}",
        )
        ok(
            f"pos_{sym}_peak",
            _num_eq(lp.peak_high, rp.peak_high),
            f"{lp.peak_high} vs {rp.peak_high}",
        )
        ok(
            f"pos_{sym}_overnight_peak",
            _num_eq(lp.overnight_peak, rp.overnight_peak),
            f"{lp.overnight_peak} vs {rp.overnight_peak}",
        )
        ok(
            f"pos_{sym}_stop_noted",
            bool(lp.stop_noted) == bool(rp.stop_noted),
            f"{lp.stop_noted} vs {rp.stop_noted}",
        )
        ok(
            f"pos_{sym}_stop_noted_px",
            _num_eq(lp.stop_noted_px, rp.stop_noted_px),
            f"{lp.stop_noted_px} vs {rp.stop_noted_px}",
        )
        ok(
            f"pos_{sym}_tp_stage",
            int(lp.tp_stage or 0) == int(rp.tp_stage or 0),
            f"{lp.tp_stage} vs {rp.tp_stage}",
        )

    ok("trade_count", len(local.trades) == len(remote.trades), "")
    loc_ids = [t.trade_id for t in local.trades]
    rem_ids = [t.trade_id for t in remote.trades]
    ok("trade_ids_unique", len(loc_ids) == len(set(loc_ids)), "")
    ok("trade_ids_equal", set(loc_ids) == set(rem_ids), "")

    la, ra = local.account, remote.account
    ok("account_cash", _num_eq(la.account_cash, ra.account_cash), f"{la.account_cash}")
    ok(
        "paper_equity_base",
        _num_eq(la.paper_equity_base, ra.paper_equity_base),
        "",
    )
    ok(
        "account_total_open",
        _num_eq(la.account_total_open, ra.account_total_open),
        "",
    )
    ok(
        "trading_session",
        str(la.trading_session_date or "")[:10]
        == str(ra.trading_session_date or "")[:10],
        "",
    )
    ok(
        "realized_keys",
        set((local.realized_today or {}).keys())
        == set((remote.realized_today or {}).keys()),
        "",
    )
    ok(
        "content_hash",
        state_content_hash(local) == state_content_hash(remote),
        f"{state_content_hash(local)} vs {state_content_hash(remote)}",
    )

    failed = [c for c in checks if not c[1]]
    return {
        "passed": len(failed) == 0,
        "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in checks],
        "failed": [n for n, o, _ in failed if not o],
    }


def _num_eq(a: Any, b: Any, eps: float = 1e-6) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= eps
    except (TypeError, ValueError):
        return a == b


def build_migration_plan(local) -> dict[str, Any]:
    return {
        "account": {
            "account_id": local.account.account_id,
            "account_cash": local.account.account_cash,
            "paper_equity_base": local.account.paper_equity_base,
            "account_total_open": local.account.account_total_open,
            "trading_session_date": local.account.trading_session_date,
        },
        "position_count": len(local.open_positions()),
        "symbols": sorted(p.symbol for p in local.open_positions()),
        "trade_count": len(local.trades),
        "daily_rows": len(local.daily),
        "realized_today_keys": sorted((local.realized_today or {}).keys()),
        "slot_queue_session": (local.slot_queue or {}).get("session"),
        "factor_memory_keys": sorted((local.factor_memory or {}).keys())[:20],
        "exit_state_fields": [
            "peak_high",
            "overnight_peak",
            "overnight_peak_session",
            "stop_noted",
            "stop_noted_px",
            "stop_noted_session",
            "tp_stage",
            "last_tp_ts",
            "available",
            "buy_time",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="holdingStocks root with holdings.json / trades.jsonl",
    )
    ap.add_argument(
        "--backend",
        default="memory",
        help="Target backend for dry-run / apply (memory|postgres). Default memory.",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Write to remote. Without this flag: dry-run only.",
    )
    ap.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write MIGRATION_VERIFICATION_REPORT JSON",
    )
    args = ap.parse_args(argv)

    holdings, trades_rows = _load_local(args.root)
    local = holdings_to_full_state(holdings, trades_rows=trades_rows)
    local_hash = state_content_hash(local)
    plan = build_migration_plan(local)

    port = create_paper_state_port(args.backend)
    before = None
    try:
        before_state = port.load_full_state(local.account.account_id)
        before = {
            "positions": len(before_state.open_positions()),
            "trades": len(before_state.trades),
            "hash": state_content_hash(before_state)
            if before_state.account.account_cash is not None
            or before_state.positions
            or before_state.trades
            else None,
        }
    except Exception as e:  # noqa: BLE001
        before = {"error": str(e)}

    report: dict[str, Any] = {
        "mode": "APPLY" if args.apply else "DRY_RUN",
        "LOCAL_STATE_HASH": local_hash,
        "REMOTE_STATE_BEFORE": before,
        "MIGRATION_PLAN": plan,
        "backend": port.backend_name(),
        "applied": False,
        "MIGRATION_DIFF": {
            "would_write_positions": plan["position_count"],
            "would_write_trades": plan["trade_count"],
            "would_write_account_cash": plan["account"]["account_cash"],
        },
    }

    if not args.apply:
        # Simulate apply into an isolated memory mirror for verification preview
        from paper_state.memory import MemoryPaperStateAdapter

        mirror = MemoryPaperStateAdapter()
        mirror.replace_full_state(local, require_lease=False)
        report["MIGRATION_VERIFICATION_REPORT"] = _verify(local, mirror.load_full_state())
        report["note"] = (
            "DRY_RUN only — remote not written. Pass --apply to write target backend."
        )
        _print_report(report)
        if args.json_out:
            args.json_out.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        return 0 if report["MIGRATION_VERIFICATION_REPORT"]["passed"] else 2

    # APPLY path (R2+; forbidden for production in R1)
    if port.backend_name() == "postgres":
        print(
            "WARNING: --apply to postgres is R2+. Ensure PAPER_DATABASE_URL is staging.",
            file=sys.stderr,
        )
    port.replace_full_state(local, require_lease=False)
    remote = port.load_full_state(local.account.account_id)
    report["applied"] = True
    report["REMOTE_STATE_AFTER_HASH"] = state_content_hash(remote)
    report["MIGRATION_VERIFICATION_REPORT"] = _verify(local, remote)
    _print_report(report)
    if args.json_out:
        args.json_out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    return 0 if report["MIGRATION_VERIFICATION_REPORT"]["passed"] else 2


def _print_report(report: dict[str, Any]) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
