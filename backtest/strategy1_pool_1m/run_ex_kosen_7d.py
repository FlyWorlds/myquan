"""近7日三槽回测，剔除科森科技；未平仓按现价结算。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "holdingStocks") not in sys.path:
    sys.path.insert(0, str(_ROOT / "holdingStocks"))

from holdingStocks.watch_config import (  # noqa: E402
    DEFAULT_ACCOUNT_TOTAL,
    MAX_PORTFOLIO_SLOTS,
    SLOT_WEIGHT,
    sina_of,
    strategy_watchlist,
)
from strategy.pullback_wave_stop import DEFAULT_ENTRY_PCT, DEFAULT_PULLBACK_PCT  # noqa: E402
from backtest.strategy1_pool_1m.run import (  # noqa: E402
    _daily,
    _minutes,
    _sina,
    simulate_portfolio_3slots,
)
from index import fetch_sina_spot  # noqa: E402

EXCLUDE = {"603626"}
OUT = _ROOT / "backtest" / "strategy1_pool_1m" / "pool_1m_7d_ex_kosen.json"


def main() -> None:
    pool = [
        w
        for w in strategy_watchlist()
        if str(w.get("code") or "").zfill(6) not in EXCLUDE
    ]
    print(f"池 {len(pool)} 只（已剔科森）· 近7日三槽", flush=True)
    entry = float(DEFAULT_ENTRY_PCT)
    pb = float(DEFAULT_PULLBACK_PCT)
    stocks = []
    for w in pool:
        code = str(w.get("code") or "").zfill(6)
        name = str(w.get("name") or code)
        sina = str(w.get("sina") or _sina(code)).lower()
        ep = float(w.get("entry_pct") or w.get("pct") or entry)
        sp = float(w.get("stop_pct") or w.get("pct") or pb)
        print(f"· {code} {name}", flush=True)
        stocks.append(
            {
                "code": code,
                "name": name,
                "entry_pct": ep,
                "pullback_pct": sp,
                "daily": _daily(sina),
                "minutes": _minutes(sina, refresh=False, days=7, source="auto"),
            }
        )

    port = simulate_portfolio_3slots(
        stocks,
        days=7,
        max_slots=MAX_PORTFOLIO_SLOTS,
        initial_cash=DEFAULT_ACCOUNT_TOTAL,
        slot_weight=SLOT_WEIGHT,
        exit_mode="half_gain",
    )
    init = float(DEFAULT_ACCOUNT_TOTAL)
    eq_rows = port.get("equity") or []
    trades = port.get("trades") or []
    opens = port.get("open_positions") or []
    cash = float(eq_rows[-1]["cash"]) if eq_rows else init

    spot_mv = 0.0
    open_mark = []
    for p in opens:
        code = str(p["code"]).zfill(6)
        shares = int(p["shares"])
        buy_px = float(p["buy_px"])
        qot = fetch_sina_spot(sina_of(code)) or {}
        spot = float(qot.get("last") or p.get("last_px") or 0)
        if spot <= 0:
            spot = float(p.get("last_px") or buy_px)
        spot_mv += spot * shares
        open_mark.append(
            {
                "code": code,
                "name": p.get("name"),
                "shares": shares,
                "buy_day": p.get("buy_day"),
                "buy_px": buy_px,
                "spot": spot,
                "pnl": round((spot - buy_px) * shares, 2),
                "pnl_pct": round((spot / buy_px - 1) * 100, 2) if buy_px else None,
            }
        )

    eq_spot = cash + spot_mv
    closed_pnl = 0.0
    for t in trades:
        if t.get("side") != "sell":
            continue
        px = float(t["px"])
        sh = int(t["shares"])
        pct = t.get("pnl_pct")
        if pct is None:
            continue
        pct = float(pct)
        buy = px / (1.0 + pct) if abs(1.0 + pct) > 1e-12 else px
        closed_pnl += (px - buy) * sh

    out = {
        "exclude": sorted(EXCLUDE),
        "n_pool": len(pool),
        "calendar": [e.get("date") for e in eq_rows],
        "init": init,
        "cash_end": cash,
        "equity_eod": float(eq_rows[-1]["equity"]) if eq_rows else None,
        "ret_eod_pct": (port.get("summary") or {}).get("return_pct"),
        "equity_spot": round(eq_spot, 2),
        "ret_spot_pct": round((eq_spot / init - 1) * 100, 2),
        "n_buys": sum(1 for t in trades if t["side"] == "buy"),
        "n_sells": sum(1 for t in trades if t["side"] == "sell"),
        "closed_pnl_amt": round(closed_pnl, 2),
        "open_float_amt": round(sum(x["pnl"] for x in open_mark), 2),
        "total_pnl_amt": round(eq_spot - init, 2),
        "open_mark": open_mark,
        "equity_curve": [
            {
                "date": e["date"],
                "equity": e["equity"],
                "ret_pct": e["ret_pct"],
                "codes": e.get("codes"),
            }
            for e in eq_rows
        ],
        "trades": trades,
        "disclaimer": "研究用途，非投资建议。已剔科森；未平仓按现价结算。",
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: out[k] for k in out if k != "trades"}, ensure_ascii=False, indent=2))
    print("--- trades ---")
    for t in trades:
        pct = t.get("pnl_pct")
        pct_s = "" if pct is None else f"{float(pct) * 100:.2f}%"
        extra = t.get("kind") or t.get("exit_reason") or t.get("source") or ""
        print(
            f"{t.get('ts')} {t['side']} {t['code']} {t['name']} "
            f"{t['px']} x{t['shares']} {extra} {pct_s}"
        )
    print(f"写入 {OUT}")


if __name__ == "__main__":
    main()
