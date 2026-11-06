"""Script to synchronize user actual holdings into the database paper ledger.

Usage:
  python scripts/sync_actual_position.py --code 002841 --name 视源股份 [--price 42.33] [--qty 1400] [--void-code 603138] [--apply]
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import json
from pathlib import Path
import sys
import uuid
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "holdingStocks"))

from database_holdings import request_state
from paper_costs import settle_trade, trade_costs
from quote_feed import fetch_sina_batch
from trade_ledger import build_ledger_entry


def symbol(c: str) -> str:
    return ("sh" if c.startswith("6") else "sz") + c


def run_sync(
    code: str,
    name: str,
    price: float | None = None,
    qty: int | None = None,
    void_code: str | None = None,
    apply: bool = False,
) -> dict:
    sym = symbol(code)
    quotes = fetch_sina_batch([sym])
    q = quotes.get(sym)
    if not q or not q.get("last"):
        raise RuntimeError(f"Failed to fetch live quote for {code}")

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    day = ts[:10]

    buy_px = round(float(price if price is not None else q["last"]), 2)
    market = "上证" if code.startswith("6") else "深证"

    # Fetch current ledger state
    state = request_state()
    before = copy.deepcopy(state)
    h = state["holdings"]
    trades = state.get("trades", [])
    ledger = state.get("ledger", {"entries": []})

    # If voiding an automated simulated position (e.g. 603138 bought today by simulation)
    void_summary = None
    if void_code and h.get("positions", {}).get(void_code, {}).get("qty", 0) > 0:
        vp = h["positions"][void_code]
        v_qty = vp["qty"]
        v_cost = vp["cost"]
        v_fees = vp.get("buy_fees_remaining", 0)
        # Revert cash
        reverted_cash = round(v_cost * v_qty + v_fees, 2)
        h["account_cash"] = round(h["account_cash"] + reverted_cash, 2)
        vp["qty"] = 0
        vp["available"] = 0
        vp["cost"] = None
        vp["today_cost"] = None
        vp["buy_time"] = None
        vp["note"] = f"同步真实持仓：撤销模拟买入 ({ts})"

        # Mark trade as archived/voided
        for t in reversed(trades):
            if t.get("code") == void_code and t.get("side") == "buy" and str(t.get("session")) == day:
                t["reset_archived"] = True
                t["archived_reason"] = f"同步真实持仓时撤销模拟买入 ({ts})"
                break
        
        # Remove matching ledger entry
        ledger_entries = ledger.get("entries", [])
        for i in range(len(ledger_entries) - 1, -1, -1):
            le = ledger_entries[i]
            if le.get("code") == void_code and le.get("side") == "buy" and str(le.get("session")) == day:
                ledger_entries.pop(i)
                break

        void_summary = {
            "code": void_code,
            "name": vp.get("name"),
            "qty": v_qty,
            "cost": v_cost,
            "reverted_cash": reverted_cash,
        }

    # Determine buy qty if not specified (target approx 60,000 RMB slot size)
    if qty is None:
        target_slot = 60000.0
        qty = int(target_slot / buy_px / 100) * 100
        if qty <= 0:
            qty = 100

    notional = round(buy_px * qty, 2)
    costs_info = trade_costs(code, "buy", buy_px, qty)
    net_cost = costs_info["net_amount"]

    if h["account_cash"] < net_cost:
        raise RuntimeError(f"Insufficient cash: available {h['account_cash']}, needed {net_cost}")

    # Start new holding
    pos = h["positions"].setdefault(code, {})
    pos.clear()
    pos.update(
        name=name,
        market=market,
        qty=qty,
        available=0,
        cost=buy_px,
        today_cost=buy_px,
        buy_time=ts,
        peak_high=buy_px,
        peak_high_at=ts,
        tp_stage=0,
        last_tp_ts=None,
        stop_noted=False,
        stop_noted_px=None,
        stop_noted_session=None,
        buy_fees_remaining=0,
        note="用户确认真实持仓买入，同步真实账本",
    )

    rec = dict(
        id="actual-buy-" + uuid.uuid4().hex,
        time=ts,
        session=day,
        side="buy",
        code=code,
        name=name,
        market=market,
        price=buy_px,
        qty=qty,
        after_qty=qty,
        cost=buy_px,
        amount=notional,
        reason="用户确认真实持仓买入",
        note="用户确认真实买入，同步真实持仓",
        fill_model="user_confirmed_actual",
        quote_source="sina",
        execution_quote_time=q.get("last_ts") or ts,
        execution_received_at=ts,
        observed_price=buy_px,
        decision_time=ts,
    )

    settle_trade(rec, h)
    h["account_cash"] = round(h["account_cash"] + rec["cash_delta"], 2)
    rec["account_cash_after"] = h["account_cash"]

    trades.append(rec)
    ledger.setdefault("entries", []).append(build_ledger_entry(rec, holdings=h))

    # Actual holdings confirmation record
    confirmation = h.setdefault("actual_holdings_confirmation", {})
    pos_conf = confirmation.setdefault("positions", {})
    if void_code:
        pos_conf.pop(void_code, None)
    pos_conf[code] = dict(
        qty=qty,
        cost=buy_px,
        cost_confirmed_at=ts,
        source="user_confirmation",
    )
    confirmation.update(
        confirmed_at=ts,
        source="user_confirmation",
    )
    h["account_execution_mode"] = "manual_actual"
    h["account_execution_mode_reason"] = "用户确认真实持仓，数量仅随用户确认的实际成交更新"

    # Pool management
    pool = h.setdefault("portfolio_pool", [])
    if code not in pool:
        pool.append(code)

    h["updated_at"] = ts
    ledger["updated_at"] = ts

    summary = {
        "apply": apply,
        "revision_before": before["revision"],
        "bought": {
            "code": code,
            "name": name,
            "price": buy_px,
            "qty": qty,
            "amount": notional,
            "fees": rec["total_fees"],
            "net_deduct": -rec["cash_delta"],
        },
        "voided": void_summary,
        "cash_before": before["holdings"]["account_cash"],
        "cash_after": h["account_cash"],
    }

    if apply:
        req_body = dict(
            expectedRevision=before["revision"],
            requestId="actual-buy-" + uuid.uuid4().hex,
            holdings=h,
            trades=trades,
            ledger=ledger,
        )
        committed = request_state("PUT", req_body)
        summary["revision_after"] = committed["revision"]

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", required=True, help="Stock code e.g. 002841")
    parser.add_argument("--name", required=True, help="Stock name e.g. 视源股份")
    parser.add_argument("--price", type=float, default=None, help="Buy price")
    parser.add_argument("--qty", type=int, default=None, help="Buy quantity")
    parser.add_argument("--void-code", type=str, default=None, help="Void simulated code e.g. 603138")
    parser.add_argument("--apply", action="store_true", help="Actually commit to Spring Boot")
    args = parser.parse_args()

    res = run_sync(
        code=args.code,
        name=args.name,
        price=args.price,
        qty=args.qty,
        void_code=args.void_code,
        apply=args.apply,
    )
    print(json.dumps(res, ensure_ascii=False, indent=2))
