"""Read-only paper cash reconciliation. Not imported by production watch."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRADES = ROOT / "trades.jsonl"
ARCHIVE = ROOT / "trades_reset_20260910_115353.jsonl"
LEDGER = ROOT / "trade_ledger.json"
HOLDINGS = ROOT / "holdings.json"
INITIAL = 300_000.0
PAPER_START = "2026-09-09"


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        rec = json.loads(s)
        if isinstance(rec, dict):
            rows.append(rec)
    return rows


def _side(rec: dict) -> str:
    s = str(rec.get("side") or "").strip().lower()
    if s in ("买", "买入", "buy"):
        return "buy"
    if s in ("卖", "卖出", "sell", "stop"):
        return "sell"
    return s


def _px_qty(rec: dict) -> tuple[float, int]:
    px = float(rec.get("price") or 0)
    qty = int(rec.get("qty") or 0)
    return px, qty


def _delta(side: str, px: float, qty: int) -> float:
    amt = round(px * qty, 2)
    if side == "buy":
        return -amt
    if side == "sell":
        return amt
    return 0.0


def _sort_key(rec: dict) -> tuple:
    return (str(rec.get("time") or ""), str(rec.get("code") or ""), _side(rec))


def replay(
    rows: list[dict],
    *,
    start_cash: float,
    start_date: str | None,
    skip_nonpositive: bool,
) -> tuple[float, list[dict], dict | None]:
    cash = round(float(start_cash), 2)
    table: list[dict] = []
    first_np: dict | None = None
    for rec in sorted(rows, key=_sort_key):
        ts = str(rec.get("time") or "")
        if start_date and ts[:10] < start_date:
            continue
        side = _side(rec)
        if side not in ("buy", "sell"):
            continue
        px, qty = _px_qty(rec)
        if px <= 0 or qty <= 0:
            continue
        delta = _delta(side, px, qty)
        before = cash
        applied = True
        if skip_nonpositive and before <= 0:
            applied = False
            after = before
        else:
            after = round(before + delta, 2)
            cash = after
        stored = rec.get("account_cash_after")
        try:
            stored_f = None if stored is None else float(stored)
        except (TypeError, ValueError):
            stored_f = None
        row = {
            "time": ts,
            "code": str(rec.get("code") or ""),
            "side": side,
            "qty": qty,
            "fill_price": px,
            "cash_delta": delta if applied else 0.0,
            "raw_delta": delta,
            "applied": applied,
            "expected_cash_after": after,
            "stored_cash": stored_f,
            "difference": None if stored_f is None else round(after - stored_f, 2),
            "note": str(rec.get("note") or rec.get("reason") or ""),
        }
        table.append(row)
        if first_np is None and after <= 0:
            first_np = dict(row)
            first_np["cash_before"] = before
    return cash, table, first_np


def position_net(rows: list[dict], start_date: str | None) -> dict[str, int]:
    qty: dict[str, int] = defaultdict(int)
    for rec in sorted(rows, key=_sort_key):
        ts = str(rec.get("time") or "")
        if start_date and ts[:10] < start_date:
            continue
        side = _side(rec)
        code = str(rec.get("code") or "").zfill(6)[-6:]
        q = int(rec.get("qty") or 0)
        if q <= 0:
            continue
        if side == "buy":
            qty[code] += q
        elif side == "sell":
            qty[code] -= q
    return dict(qty)


def main() -> None:
    trades = _load_jsonl(TRADES)
    arch = _load_jsonl(ARCHIVE)
    holdings = json.loads(HOLDINGS.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.is_file() else {}
    entries = ledger.get("entries") if isinstance(ledger, dict) else []
    entries = entries if isinstance(entries, list) else []

    stored = holdings.get("account_cash")
    total = holdings.get("account_total")
    open_eq = holdings.get("account_total_open")
    base = holdings.get("paper_equity_base")
    print("STORED", stored, "TOTAL", total, "OPEN", open_eq, "BASE", base)
    print("TRADES", len(trades), "ARCHIVE", len(arch), "LEDGER", len(entries))

    for label, start, skip in (
        ("all_always", None, False),
        ("from_0909_always", PAPER_START, False),
        ("from_0909_oldbug", PAPER_START, True),
        ("from_0910_always", "2026-09-10", False),
        ("from_0910_oldbug", "2026-09-10", True),
    ):
        cash, table, first_np = replay(
            trades, start_cash=INITIAL, start_date=start, skip_nonpositive=skip
        )
        skipped = sum(1 for r in table if not r["applied"])
        print(
            f"{label}: cash={cash} n={len(table)} skipped={skipped} "
            f"first_np={None if not first_np else (first_np['time'], first_np['code'], first_np['side'], first_np['cash_before'], first_np['expected_cash_after'])}"
        )

    cash_ok, table_ok, first_ok = replay(
        trades, start_cash=INITIAL, start_date=PAPER_START, skip_nonpositive=False
    )
    cash_bug, table_bug, first_bug = replay(
        trades, start_cash=INITIAL, start_date=PAPER_START, skip_nonpositive=True
    )
    print("FIRST_NP_ALWAYS", first_ok)
    print("FIRST_NP_OLDBUG", first_bug)

    today = [r for r in table_ok if r["time"].startswith("2026-09-18")]
    print("TODAY_ALWAYS_NET", round(sum(r["raw_delta"] for r in today), 2), "n", len(today))
    print("TODAY_ROWS")
    for r in today:
        print(
            f"  {r['time']} {r['side']:4} {r['code']} qty={r['qty']} px={r['fill_price']} "
            f"d={r['raw_delta']} after={r['expected_cash_after']} stored={r['stored_cash']} applied={r['applied']}"
        )

    today_bug = [r for r in table_bug if r["time"].startswith("2026-09-18")]
    print("TODAY_BUG_AFTER", today_bug[-1]["expected_cash_after"] if today_bug else None)

    pos = holdings.get("positions") or {}
    book_qty = {
        str(c).zfill(6)[-6:]: int(p.get("qty") or 0)
        for c, p in pos.items()
        if isinstance(p, dict) and int(p.get("qty") or 0) > 0
    }
    net_all = {c: q for c, q in position_net(trades, None).items() if q != 0}
    net_0909 = {c: q for c, q in position_net(trades, PAPER_START).items() if q != 0}
    print("BOOK_QTY", book_qty)
    print("NET_ALL", net_all)
    print("NET_0909", net_0909)
    missing = sorted(set(book_qty) | set(net_0909))
    for c in missing:
        b = book_qty.get(c, 0)
        n = net_0909.get(c, 0)
        if b != n:
            print("QTY_MISMATCH", c, "book", b, "net_from_0909_trades", n)

    rt = holdings.get("realized_today") or {}
    print("REALIZED_TODAY", list(rt) if isinstance(rt, dict) else rt)

    notes = set()
    for r in trades:
        note = str(r.get("note") or "")
        if any(k in note for k in ("手动", "CLI", "纠", "校正", "确认", "现金")):
            notes.add(note)
    print("SPECIAL_NOTES", sorted(notes)[:30])

    sett = holdings.get("daily_settlements") or {}
    for day in sorted(sett):
        rec = sett[day]
        if not isinstance(rec, dict):
            continue
        print(
            "SETTLE",
            day,
            "total",
            rec.get("account_total"),
            "open",
            rec.get("account_open"),
            "day",
            rec.get("day_pnl"),
            "eqday",
            rec.get("equity_day_pnl"),
            "gap",
            rec.get("day_pnl_vs_equity"),
        )

    print("REPLAY_0909_ALWAYS", cash_ok)
    print("REPLAY_0909_OLDBUG", cash_bug)

    after_sync = [
        r for r in trades if str(r.get("time") or "") > "2026-09-14 09:06:57"
    ]
    print("TRADES_AFTER_LEDGER_SYNC", len(after_sync))
    for skip in (False, True):
        cash, table, first_np = replay(
            after_sync, start_cash=35371.0, start_date=None, skip_nonpositive=skip
        )
        print(
            "FROM_0914_CASH35371",
            "oldbug" if skip else "always",
            "cash",
            cash,
            "first_np",
            None
            if not first_np
            else (
                first_np["time"],
                first_np["code"],
                first_np["side"],
                first_np["cash_before"],
                first_np["expected_cash_after"],
            ),
        )
        if not skip:
            for r in table:
                print(
                    f"  {r['time']} {r['side']:4} {r['code']} d={r['raw_delta']} "
                    f"after={r['expected_cash_after']} stored={r['stored_cash']} "
                    f"applied={r['applied']}"
                )

    # ledger vs jsonl counts
    print("LEDGER_SIDES", len(entries), "JSONL", len(trades))


def _ledger_branch_cash() -> None:
    import subprocess

    proc = subprocess.run(
        ["git", "show", "origin/holdings-ledger:holdingStocks/holdings.json"],
        cwd=str(ROOT.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        print("LEDGER_BRANCH_FAIL", proc.stderr[:300])
        return
    raw = "".join(ch if ord(ch) >= 32 or ch in "\n\r\t" else " " for ch in proc.stdout)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print("LEDGER_BRANCH_JSON_FAIL", e)
        return
    print(
        "LEDGER_BRANCH",
        "updated",
        data.get("updated_at"),
        "cash",
        data.get("account_cash"),
        "total",
        data.get("account_total"),
        "open",
        data.get("account_total_open"),
        "base",
        data.get("paper_equity_base"),
    )
    pos = {
        str(c): int(p.get("qty") or 0)
        for c, p in (data.get("positions") or {}).items()
        if isinstance(p, dict) and int(p.get("qty") or 0) > 0
    }
    print("LEDGER_BRANCH_POS", pos)


if __name__ == "__main__":
    main()
    _ledger_branch_cash()
