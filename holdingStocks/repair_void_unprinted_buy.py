"""作废「最高未印到核定买点」的纸面 BUY（默认 dry-run）。

背景：2026-10-12 五方光电 002962 —— 今开 14.83 / 最高 14.87 / 核定买点 15.21，
09:30 却按现价 14.33 入槽。根因已修（核定买点 + 最高须印到），本脚本只清账：
视同从未买入（加回现金、清仓、不作一笔亏损卖出）。

  python repair_void_unprinted_buy.py --code 002962 --buy-time "2026-10-12 09:30:00"
  python repair_void_unprinted_buy.py ... --apply      # 须先停 watch

同时把当日 strategy simulator 的假 BUY 移入 strategy_signal_events.voided.json，
对应账本打回 FLAT（保留 pnl_start_reset bootstrap 标记，避免日线回灌）。
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
SIM_STATE = HERE / "strategy_sim_state.json"
SIM_EVENTS = HERE / "strategy_signal_events.json"
SIM_VOIDED = HERE / "strategy_signal_events.voided.json"


def _code6(code: str) -> str:
    return str(code or "").zfill(6)[-6:]


def _is_buy(t: dict[str, Any], code: str, buy_time: str) -> bool:
    return (
        _code6(str(t.get("code") or "")) == code
        and str(t.get("side")) == "buy"
        and str(t.get("time")) == buy_time
    )


def _empty_pos(name: str, market: str) -> dict[str, Any]:
    return {
        "name": name,
        "market": market,
        "qty": 0,
        "available": None,
        "cost": None,
        "today_cost": None,
        "buy_time": None,
        "tp_stage": 0,
        "last_tp_ts": None,
        "note": "",
    }


def _void_paper(
    code: str, buy_time: str
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any], float]:
    trades = [json.loads(x) for x in TRADES.read_text(encoding="utf-8").splitlines() if x.strip()]
    hits = [i for i, t in enumerate(trades) if _is_buy(t, code, buy_time)]
    if not hits:
        raise SystemExit(f"找不到 BUY {code} @ {buy_time}")
    if len(hits) > 1:
        raise SystemExit(f"BUY {code} @ {buy_time} 多于一笔")
    bi = hits[0]
    buy = trades[bi]
    later_sell = next(
        (
            t
            for t in trades[bi + 1 :]
            if _code6(str(t.get("code") or "")) == code and str(t.get("side")) == "sell"
        ),
        None,
    )
    if later_sell is not None:
        raise SystemExit("其后已有 SELL，请改用 repair_void_stale_buy.py")
    buy_amt = float(buy.get("amount") or float(buy["price"]) * int(buy["qty"]))
    print(f"作废 BUY #{bi} {buy['time']} {code} {buy['qty']}@{buy['price']} = {buy_amt:,.2f}")
    new_trades = [t for i, t in enumerate(trades) if i != bi]

    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ents = list(ledger.get("entries") or [])
    lhits = [i for i, t in enumerate(ents) if _is_buy(t, code, buy_time)]
    if lhits:
        ledger["entries"] = [e for i, e in enumerate(ents) if i != lhits[0]]
        print(f"trade_ledger 删除 #{lhits[0]}")

    h = json.loads(HOLDINGS.read_text(encoding="utf-8"))
    if h.get("account_cash") is not None:
        old = float(h["account_cash"])
        h["account_cash"] = round(old + buy_amt, 2)
        print(f"account_cash {old:,.2f} -> {h['account_cash']:,.2f}")
    pos = (h.get("positions") or {}).get(code)
    name = str((pos or {}).get("name") or buy.get("name") or code)
    market = str((pos or {}).get("market") or buy.get("market") or "")
    h.setdefault("positions", {})[code] = _empty_pos(name, market)
    print(f"positions.{code} 清成空仓")
    for bucket in ("alert_sticky", "realized_today", "closed_today"):
        m = h.get(bucket)
        if isinstance(m, dict) and code in m:
            m.pop(code)
            print(f"删除 {bucket}.{code}")
    fm = (h.get("factor_memory") or {}).get(code)
    sess = str(buy.get("session") or buy_time[:10])
    if isinstance(fm, dict) and sess in (
        str(fm.get("last_buy_factor_date") or "")[:10],
        str(fm.get("last_sell_factor_date") or "")[:10],
    ):
        h["factor_memory"].pop(code)
        print(f"删除 factor_memory.{code}")
    draft = (h.get("day_settlements") or {}).get(sess)
    if isinstance(draft, dict):
        for key in ("positions", "closing_marks"):
            rows = draft.get(key)
            if isinstance(rows, list):
                n0 = len(rows)
                draft[key] = [r for r in rows if _code6(str(r.get("code") or "")) != code]
                if len(draft[key]) != n0:
                    print(f"day_settlements.{sess}.{key} 去掉 {code}")
    return buy, new_trades, ledger, h, buy_amt


def _void_simulator(code: str, session: str) -> None:
    if not SIM_STATE.exists() or not SIM_EVENTS.exists():
        print("无 simulator 账本，跳过")
        return
    state = json.loads(SIM_STATE.read_text(encoding="utf-8"))
    events = json.loads(SIM_EVENTS.read_text(encoding="utf-8"))
    evs = list(events.get("events") or [])
    keep: list[dict[str, Any]] = []
    voided: list[dict[str, Any]] = []
    touched: set[str] = set()
    for e in evs:
        same = (
            _code6(str(e.get("symbol") or "")) == code
            and str(e.get("side") or "").upper() == "BUY"
            and str(e.get("trading_session_date") or e.get("trigger_time") or "")[:10] == session
        )
        if same:
            rec = dict(e)
            rec["voided_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rec["void_reason"] = "BUY_NOT_PRINTED"
            voided.append(rec)
            touched.add(f"{e.get('strategy_id')}:{code}")
        else:
            keep.append(e)
    if not voided:
        print("simulator 无当日 BUY 事件")
        return
    pos = state.setdefault("positions", {})
    for key in list(pos.keys()):
        book = pos.get(key)
        if not isinstance(book, dict):
            continue
        if _code6(str(book.get("symbol") or key.split(":")[-1])) != code:
            continue
        if key not in touched and str(book.get("entry_time") or "")[:10] != session:
            continue
        kept_boot = {
            "bootstrapped": book.get("bootstrapped"),
            "bootstrap_cutoff": book.get("bootstrap_cutoff"),
            "bootstrap_source": book.get("bootstrap_source"),
            "bootstrap_model": book.get("bootstrap_model"),
        }
        init = float(book.get("initial_cash") or 100000.0)
        pos[key] = {
            **book,
            "state": "FLAT",
            "entry_price": None,
            "entry_time": None,
            "exit_price": None,
            "exit_time": None,
            "virtual_cash": init,
            "virtual_shares": 0.0,
            "trades": 0,
            "last_mark": None,
            "last_quote_ts": None,
            "cumulative_return_pct": 0.0,
            "single_return_pct": None,
            "closed_trade_return_pct": None,
            "gap_rebuy_ok": False,
            **{k: v for k, v in kept_boot.items() if v is not None},
        }
        print(f"simulator {key} LONG -> FLAT 现金{init:.0f}")
    events["events"] = keep
    events["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    state["updated_at"] = events["updated_at"]
    prev = []
    if SIM_VOIDED.exists():
        raw = json.loads(SIM_VOIDED.read_text(encoding="utf-8"))
        prev = list(raw.get("events") or raw) if isinstance(raw, dict) else list(raw)
    SIM_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    SIM_EVENTS.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    SIM_VOIDED.write_text(
        json.dumps({"updated_at": events["updated_at"], "events": prev + voided}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"simulator 作废 {len(voided)} 笔 BUY -> {SIM_VOIDED.name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--buy-time", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    code = _code6(a.code)
    session = str(a.buy_time)[:10]

    if a.apply:
        import index as idx

        if idx._read_watch_lock():
            raise SystemExit("watch 仍在运行（holdings_watch.pid），请先停掉再 --apply")

    buy, new_trades, ledger, holdings, _amt = _void_paper(code, a.buy_time)
    if not a.apply:
        print("\n(dry-run) 未写盘；确认后加 --apply")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for p in (TRADES, LEDGER, HOLDINGS, SIM_STATE, SIM_EVENTS):
        if p.exists():
            shutil.copy2(p, p.with_name(f"{p.name}.bak_{stamp}"))
    rec = dict(buy)
    rec["voided_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rec["voided_reason"] = "BUY_NOT_PRINTED"
    with VOIDED.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    TRADES.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in new_trades), encoding="utf-8")
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    write_json_locked(HOLDINGS, json.dumps(holdings, ensure_ascii=False, indent=2))
    _void_simulator(code, session)
    print(f"\n已写盘；备份后缀 .bak_{stamp}；作废记录 -> {VOIDED.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
