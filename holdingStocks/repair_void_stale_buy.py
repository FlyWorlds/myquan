"""作废「跨日粘滞伪触买」产生的纸面 BUY + 随后的 SELL（默认 dry-run）。

背景：2026-09-29 金安国纪 002636 —— 昨日 buy_touched 被今日粘滞继承，09:30 腾槽现价买入，
buy_time 记成昨日 09:46 绕过 T+1，09:30:15 止损卖出。根因已修（_sticky_same_session /
STALE_BUY_TRIGGER），本脚本只清账：视同从未买入。

  python repair_void_stale_buy.py --code 002636 --buy-time "2026-09-28 09:46:00" --session 2026-09-29
  python repair_void_stale_buy.py ... --apply      # 须先停 watch

改动：trades.jsonl / trade_ledger.json 删两笔并修正其后 account_cash_after；
holdings.json 现金加回净差、删 realized_today/closed_today/alert_sticky/当日 factor_memory、
清仓位止损备注。作废记录写入 trades.voided.jsonl；三个文件先备份 .bak_{stamp}。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from holdings_store import write_json_locked  # noqa: E402

TRADES = HERE / "trades.jsonl"
LEDGER = HERE / "trade_ledger.json"
HOLDINGS = HERE / "holdings.json"
VOIDED = HERE / "trades.voided.jsonl"


def _is_target(t: dict[str, Any], code: str, side: str, pred) -> bool:
    return str(t.get("code") or "").zfill(6)[-6:] == code and str(t.get("side")) == side and pred(t)


def _locate(rows: list[dict[str, Any]], code: str, buy_time: str, session: str) -> tuple[int, int]:
    bi = next(
        (i for i, t in enumerate(rows) if _is_target(t, code, "buy", lambda x: str(x.get("time")) == buy_time)),
        -1,
    )
    if bi < 0:
        raise SystemExit(f"找不到 BUY {code} @ {buy_time}")
    si = next(
        (
            i
            for i, t in enumerate(rows)
            if _is_target(
                t,
                code,
                "sell",
                lambda x: str(x.get("time", ""))[:10] == session and str(x.get("buy_time") or "") == buy_time,
            )
        ),
        -1,
    )
    if si < 0:
        raise SystemExit(f"找不到对应 SELL {code} session={session} buy_time={buy_time}")
    return bi, si


def _shift_cash(rows: list[dict[str, Any]], bi: int, si: int, buy_amt: float, sell_amt: float) -> list[str]:
    """按写入方向修正 account_cash_after：买后卖前 +buy_amt；卖后 +(buy_amt-sell_amt)。"""
    step = 1 if bi < si else -1
    log: list[str] = []
    i = bi + step
    while 0 <= i < len(rows):
        if i == si:
            i += step
            continue
        between = (step == 1 and i < si) or (step == -1 and i > si)
        delta = buy_amt if between else round(buy_amt - sell_amt, 2)
        t = rows[i]
        if t.get("account_cash_after") is not None:
            old = float(t["account_cash_after"])
            t["account_cash_after"] = round(old + delta, 2)
            log.append(f"  {t.get('time')} {t.get('side')} {t.get('code')} cash_after {old:,.2f} -> {t['account_cash_after']:,.2f}")
        i += step
    return log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--buy-time", required=True, help="被错记的 BUY time，如 2026-09-28 09:46:00")
    ap.add_argument("--session", required=True, help="实际发生（卖出）的交易日")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    code = a.code.zfill(6)[-6:]

    if a.apply:
        sys.path.insert(0, str(HERE))
        sys.path.insert(0, str(HERE.parent))
        import index as idx

        if idx._read_watch_lock():
            raise SystemExit("watch 仍在运行（holdings_watch.pid），请先停掉再 --apply")

    trades = [json.loads(x) for x in TRADES.read_text(encoding="utf-8").splitlines() if x.strip()]
    bi, si = _locate(trades, code, a.buy_time, a.session)
    buy, sell = trades[bi], trades[si]
    buy_amt = float(buy.get("amount") or float(buy["price"]) * int(buy["qty"]))
    sell_amt = float(sell.get("amount") or float(sell["price"]) * int(sell["qty"]))
    net = round(buy_amt - sell_amt, 2)
    print(f"作废 BUY  #{bi} {buy['time']} {code} {buy['qty']}@{buy['price']} = {buy_amt:,.2f}")
    print(f"作废 SELL #{si} {sell['time']} {code} {sell['qty']}@{sell['price']} = {sell_amt:,.2f}  day_pnl={sell.get('day_pnl')}")
    print(f"现金净差加回 +{net:,.2f}")
    print("trades.jsonl 现金余额修正:")
    for s in _shift_cash(trades, bi, si, buy_amt, sell_amt):
        print(s)
    new_trades = [t for i, t in enumerate(trades) if i not in (bi, si)]

    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ents = ledger.get("entries") or []
    lbi, lsi = _locate(ents, code, a.buy_time, a.session)
    print("trade_ledger.json 现金余额修正:")
    for s in _shift_cash(ents, lbi, lsi, buy_amt, sell_amt):
        print(s)
    ledger["entries"] = [e for i, e in enumerate(ents) if i not in (lbi, lsi)]

    h = json.loads(HOLDINGS.read_text(encoding="utf-8"))
    changes: list[str] = []
    if h.get("account_cash") is not None:
        old = float(h["account_cash"])
        h["account_cash"] = round(old + net, 2)
        changes.append(f"account_cash {old:,.2f} -> {h['account_cash']:,.2f}")
    for bucket in ("realized_today", "closed_today", "alert_sticky"):
        m = h.get(bucket)
        if isinstance(m, dict) and code in m:
            m.pop(code)
            changes.append(f"删除 {bucket}.{code}")
    fm = (h.get("factor_memory") or {}).get(code)
    if isinstance(fm, dict) and a.session in (
        str(fm.get("last_buy_factor_date")),
        str(fm.get("last_sell_factor_date")),
    ):
        h["factor_memory"].pop(code)
        changes.append(f"删除 factor_memory.{code}（当日写入）")
    pos = (h.get("positions") or {}).get(code)
    if isinstance(pos, dict) and int(pos.get("qty") or 0) == 0:
        for k in ("note", "peak_high", "peak_high_at", "overnight_peak", "overnight_peak_session"):
            pos[k] = "" if k == "note" else None
        changes.append(f"清 positions.{code} 止损备注/峰值")
    print("holdings.json:")
    for c in changes:
        print("  " + c)

    if not a.apply:
        print("\n(dry-run) 未写盘；确认后加 --apply")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for p in (TRADES, LEDGER, HOLDINGS):
        shutil.copy2(p, p.with_name(f"{p.name}.bak_{stamp}"))
    with VOIDED.open("a", encoding="utf-8") as f:
        for t in (buy, sell):
            rec = dict(t)
            rec["voided_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rec["voided_reason"] = "STALE_STICKY_CROSSDAY_BUY"
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    TRADES.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in new_trades), encoding="utf-8")
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    write_json_locked(HOLDINGS, json.dumps(h, ensure_ascii=False, indent=2))
    print(f"\n已写盘；备份后缀 .bak_{stamp}；作废记录 -> {VOIDED.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
