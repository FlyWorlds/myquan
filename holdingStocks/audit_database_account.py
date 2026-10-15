"""Read-only database audit; page lag and legacy history are not silently repaired."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from account_reconciliation import AccountReadModel, effective_deliveries, number
from boot_holdings import build_boot_holdings
from database_holdings import request_state
from database_quotes import read_quotes
from database_strategy_books import request_books

ROOT = Path(__file__).resolve().parent


def strategy_arithmetic(books):
    issues, pending = [], []
    for code, book in books.items():
        if book.get("history_status") == "legacy_checkpoint_unverified":
            pending.append(code)
        try:
            def decimal(key, default=None):
                raw = book.get(key, default)
                value = Decimal(str(raw))
                if not value.is_finite():
                    raise ValueError(key)
                return value
            qty, initial, cash = decimal("virtual_shares"), decimal("initial_cash"), decimal("virtual_cash")
            if qty < 0 or qty != qty.to_integral_value() or initial <= 0 or cash < 0:
                raise ValueError("Invalid strategy amounts")
            entry = decimal("entry_price") if qty else Decimal(0)
            mark = decimal("last_mark") if qty else Decimal(0)
            if qty and (entry <= 0 or mark <= 0):
                raise ValueError("Missing strategy cost/mark")
            floating = (mark-entry)*qty
            total = cash+mark*qty-initial
            cycle = decimal("single_realized_pnl", 0)+floating
            expected = dict(total_pnl=total, unrealized_pnl=floating,
                            realized_pnl=total-floating, cycle_pnl=cycle,
                            since_checkpoint_pnl=total-decimal("checkpoint_total_pnl", 0))
            for key, value in expected.items():
                if abs(decimal(key)-value) > Decimal("0.01"):
                    issues.append(dict(kind="strategy_amount_mismatch", code=code, field=key,
                                       expected=str(value), recorded=str(book.get(key))))
            percentages = dict(cumulative_return_pct=total/initial*100)
            basis = decimal("single_cost_base", 0)
            if qty:
                percentages["single_return_pct"] = (mark-entry)/entry*100
            if basis > 0:
                percentages["cycle_return_pct"] = cycle/basis*100
                if not qty:
                    percentages["single_return_pct"] = cycle/basis*100
            elif cycle:
                issues.append(dict(kind="strategy_cycle_basis_unavailable", code=code))
            for key, value in percentages.items():
                if abs(decimal(key)-value) > Decimal("0.000001"):
                    issues.append(dict(kind="strategy_percentage_mismatch", code=code, field=key))
        except (InvalidOperation, ValueError, TypeError, ArithmeticError):
            issues.append(dict(kind="strategy_basis_unavailable", code=code))
    return issues, pending


def audit(state, snapshot, books, quotes, *, clock=None):
    entries, issues = effective_deliveries(state)
    seen = set()
    quantities = {}
    for entry in entries:
        code, side = entry.get("code"), entry.get("side")
        if not entry.get("id"):
            issues.append(dict(kind="missing_delivery_id", entry_id=entry.get("id")))
        elif entry.get("id") in seen:
            issues.append(dict(kind="duplicate_delivery_id", entry_id=entry.get("id")))
        seen.add(entry.get("id"))
        if side not in ("buy", "sell"):
            continue
        qty, after = int(entry.get("qty") or 0), int(entry.get("after_qty") or 0)
        if qty <= 0 or after < 0:
            issues.append(dict(kind="invalid_delivery_quantity", entry_id=entry.get("id")))
            continue
        before = after + qty if side == "sell" else after - qty
        if code in quantities and quantities[code] != before:
            issues.append(dict(kind="position_chain_gap", code=code, entry_id=entry.get("id"),
                               expected_before=quantities[code], recorded_before=before))
        quantities[code] = after
    for code, after in quantities.items():
        held = int(state["holdings"].get("positions", {}).get(code, {}).get("qty") or 0)
        if held != after:
            issues.append(dict(kind="delivery_position_mismatch", code=code, recorded_after=after, current_qty=held))
    strategy_issues, history_pending = strategy_arithmetic(books)
    session = state["holdings"].get("last_session") or (clock or datetime.now().isoformat())[:10]
    model = AccountReadModel(state)
    rows, summary = build_boot_holdings(model, session=session, clock=clock or str(datetime.now()),
                                       get_quote=lambda sina: quotes.get(sina))
    ui_revision = (snapshot or {}).get("paperRevision")
    ui_comparable = ui_revision == state["revision"]
    # UI and DB prices may be from different instants even when the account revision matches.
    page_rows = {r.get("代码"): r for r in (snapshot or {}).get("holdings", [])}
    if ui_comparable:
        ui_comparable = all(code in page_rows and row.get("报价数据库版本") is not None
                            and page_rows[code].get("更新") == row.get("更新")
                            and page_rows[code].get("报价数据库版本") == row.get("报价数据库版本")
                            for row in rows if (code := row["代码"]))
    ui_issues = []
    if ui_comparable:
        if len(page_rows) != len([r for r in (snapshot or {}).get("holdings", [])]):
            ui_issues.append(dict(kind="duplicate_ui_rows"))
        for row in rows:
            shown_row = page_rows[row["代码"]]
            for key in ("现价", "持仓", "成本"):
                if number(row.get(key)) != number(shown_row.get(key)):
                    ui_issues.append(dict(kind="ui_row_mismatch", code=row["代码"], field=key))
        for key in ("availableCash", "accountTotal", "totalPnl", "dayPnl", "positionPct"):
            value, shown = number(summary.get(key)), number((snapshot.get("account") or {}).get(key))
            if value is not None and (shown is None or abs(value-shown) > .01):
                ui_issues.append(dict(kind="ui_value_mismatch", field=key, expected=value, shown=shown))
    valuation_ready = summary["accountTotal"] is not None and summary["dayPnlVsEquity"] == 0
    operational = not issues and not strategy_issues and not summary["reconciliationIssues"] and valuation_ready
    return dict(scope="database_amounts_position_chain_and_comparable_ui_only",
                revision=state["revision"], account=summary, deliveryIssues=issues,
                strategyIssues=strategy_issues,
                strategyHistoryPending=history_pending,
                strategyBookRevisions={code: book.get("revision") for code, book in books.items()},
                valuationQuotes={row["代码"]: dict(time=row.get("更新"), price=row.get("现价"),
                                    revision=row.get("报价数据库版本")) for row in rows},
                uiRevision=ui_revision, uiComparable=ui_comparable, uiIssues=ui_issues,
                uiStatus="compared" if ui_comparable else "pending_matching_account_revision_and_quote_time",
                originalDeliveries=len(state["ledger"]["entries"]), effectiveDeliveries=len(entries),
                correctedFills=[e for e in entries if e.get("adjustment_ids")],
                writesPerformed=False, operationalChecksPassed=operational,
                legacyHistoryResolved=not history_pending, historyVerified=False, eventHistoryChecked=False,
                complete=operational and not history_pending and ui_comparable and not ui_issues)


def coherent_database_read(*, attempts=3):
    for _ in range(attempts):
        state = request_state()
        quotes = read_quotes()
        books = request_books()
        if request_state()["revision"] == state["revision"]:
            return state, quotes, books
        time.sleep(.15)
    raise RuntimeError("Account changed during audit; retry in a quiet period, no repair performed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT.parent / "backend/logs/account-audit.json")
    parser.add_argument("--watch-url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    state, quotes, books = coherent_database_read()
    try:
        with urlopen(args.watch_url.rstrip("/")+"/api/snapshot", timeout=3) as response:
            snapshot = json.load(response)
    except (OSError, ValueError):
        snapshot = None
    result = audit(state, snapshot, books, quotes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(args.out)
    print(json.dumps({k: result[k] for k in ("scope", "revision", "operationalChecksPassed", "complete",
        "uiStatus", "uiIssues", "legacyHistoryResolved", "historyVerified", "eventHistoryChecked",
        "deliveryIssues", "strategyIssues")}, ensure_ascii=False))
    return 0 if result["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
