"""Read-only audit of one database revision and stable simulator/event files."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from account_reconciliation import account_summary, effective_deliveries, number
from database_holdings import request_state

ROOT = Path(__file__).resolve().parent


def audit(state, snapshot, sim, events):
    entries, issues = effective_deliveries(state)
    seen = set()
    quantities = {}
    for entry in entries:
        code, side = entry.get("code"), entry.get("side")
        if entry.get("id") in seen:
            issues.append(dict(kind="duplicate_delivery_id", entry_id=entry.get("id")))
        seen.add(entry.get("id"))
        if side not in ("buy", "sell"):
            continue
        qty, after = int(entry.get("qty") or 0), int(entry.get("after_qty") or 0)
        before = after + qty if side == "sell" else after - qty
        if code in quantities and quantities[code] != before:
            issues.append(dict(kind="position_chain_gap", code=code, entry_id=entry.get("id"),
                               expected_before=quantities[code], recorded_before=before))
        quantities[code] = after
    strategy_issues = []
    for key, pos in sim.get("positions", {}).items():
        if pos.get("strategy_id") != "strategy16" or pos.get("entry_price") is None:
            continue
        buys = [e for e in events.get("events", []) if e.get("strategy_id") == "strategy16"
                and e.get("symbol") == pos.get("symbol") and e.get("side") == "BUY"
                and e.get("trigger_time") == pos.get("entry_time")]
        if len(buys) != 1 or number(buys[0].get("trigger_price")) != number(pos["entry_price"]):
            strategy_issues.append(dict(kind="missing_entry_event" if not buys else "simulator_entry_event_mismatch", key=key,
                        entry_price=pos["entry_price"], entry_time=pos.get("entry_time"),
                        event_prices=[e.get("trigger_price") for e in buys]))
    summary = account_summary(state, snapshot.get("holdings", []), state["holdings"]["last_session"])
    return dict(revision=state["revision"], account=summary, deliveryIssues=issues,
                strategyIssues=strategy_issues,
                originalDeliveries=len(state["ledger"]["entries"]), effectiveDeliveries=len(entries),
                correctedFills=[e for e in entries if e.get("adjustment_ids")],
                writesPerformed=False, complete=not issues and not strategy_issues
                and summary["accountTotal"] is not None and summary["dayPnlVsEquity"] == 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT.parent / "backend/logs/account-audit.json")
    args = parser.parse_args()
    state = request_state()
    with urlopen("http://127.0.0.1:8765/api/snapshot", timeout=5) as response:
        snapshot = json.load(response)
    paths = [ROOT / "strategy_sim_state.json", ROOT / "strategy_signal_events.json"]
    for attempt in range(3):
        before = [p.stat().st_mtime_ns for p in paths]
        sim, events = [json.loads(p.read_text()) for p in paths]
        if before == [p.stat().st_mtime_ns for p in paths]:
            break
    else:
        raise RuntimeError("Simulator files changed during audit; retry")
    result = audit(state, snapshot, sim, events)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(args.out)
    print(json.dumps({k: result[k] for k in ("revision", "complete", "deliveryIssues", "strategyIssues")}, ensure_ascii=False))
    return 0 if result["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
