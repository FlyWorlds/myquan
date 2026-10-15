"""Offline fixed-entry exit comparison; minute-close proxies are NOT historical ticks."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "holdingStocks"))
from quote_exit import evaluate_quote_exit, overnight_note_updates
from strategy.pullback_wave_stop import eval_multi_tp_bar, realized_vol_daily, resolve_t1_overnight_note
from strategy.exit_rules.overnight_open_protect import evaluate_overnight_open_protect
from backtest.strategy1_pool_1m import run as fees


def simulate(entry, bars, daily, *, mode, end):
    qty, cost = int(entry.shares), float(entry.px)
    pos = dict(qty=qty, available=0, cost=cost, buy_time=str(entry.ts), peak_high=cost, tp_stage=0)
    selected = bars[(bars.ts > pd.Timestamp(entry.ts)) & (bars.ts < pd.Timestamp(end) + pd.Timedelta(days=1))]
    if selected.empty:
        raise ValueError(f"No post-entry coverage: {entry.code}")
    legs, old_session_peak = [], 0.
    session = None
    for bar in selected.itertuples():
        day = bar.ts.strftime("%Y-%m-%d")
        previous = daily[daily.date < pd.Timestamp(day)]
        prev_close = float(previous.iloc[-1].close) if not previous.empty else None
        vol = realized_vol_daily(previous.close.tolist())
        day_bars = bars[bars.ts.dt.strftime("%Y-%m-%d") == day]
        opening = float(day_bars.iloc[0].open)
        overnight = str(entry.ts)[:10] < day
        if session != day:
            session, old_session_peak = day, 0.
            pos["available"] = pos["qty"] if overnight else 0
            # Both arms get the SAME opening-protection formula and evidence.
            if overnight:
                pos.update(overnight_note_updates(pos, {"prev_close": prev_close}, day))
                protect = evaluate_overnight_open_protect(dict(cost=cost, open_px=opening,
                    prev_close=prev_close, peak_high=pos["peak_high"], qty=pos["qty"],
                    buy_time=pos["buy_time"], session=day, overnight_high_ok=True))
                if protect.triggered:
                    legs.append(dict(time=day+" 09:30:00", price=opening, qty=pos["qty"], reason="open_protect"))
                    pos["qty"] = 0
                    break
        at = bar.ts.to_pydatetime()
        if mode == "minute_ohlc":
            event = eval_multi_tp_bar(bar_open=float(bar.open), bar_high=float(bar.high), bar_low=float(bar.low),
                cost_px=cost, peak_before=pos["peak_high"], shares=pos["qty"], tp_stage=pos["tp_stage"],
                can_sell=overnight, overnight_armed=overnight and bool(pos.get("stop_noted")),
                day_open=opening, vol20_daily=vol, session_peak_before=old_session_peak)
            pos["peak_high"], old_session_peak = event["peak_after"], event["session_peak_after"]
            if not overnight and event.get("tp_marked") and event.get("noted_px"):
                pos["stop_noted"] = True
            if not overnight:
                pos["held_low"] = min(float(pos.get("held_low") or cost), float(bar.low))
                note = resolve_t1_overnight_note(cost_px=cost, peak_high=pos["peak_high"],
                    close_px=float(bar.close), bar_low=pos["held_low"])
                if note["reason"] == "profit_ge_3pct":
                    pos["stop_noted"] = False
                elif note.get("noted_px") and (note["reason"] == "hard_from_cost" or at.strftime("%H:%M:%S") >= "14:57:00"):
                    pos["stop_noted"] = True
            action = event["action"]
        else:
            quote = dict(session=day, last_ts=str(bar.ts), last=float(bar.close), open=opening,
                high=max(opening, float(bar.close)), low=min(opening, float(bar.close)),
                prev_close=prev_close, _quote_source="minute_close_proxy", _open_finalized=True)
            event = evaluate_quote_exit(pos, quote, session=day, now=at, received_at=at, vol20_daily=vol)
            if event is None:
                continue
            pos.update(event["updates"])
            pos["quote_exit_watermark"] = event["watermark"]
            action = event["action"]
        if action:
            sold = min(pos["qty"], int(action["shares"]))
            legs.append(dict(time=str(bar.ts), price=float(action["fill_px"]), qty=sold, reason=action["reason"]))
            pos["qty"] -= sold
            pos["available"] = pos["qty"]
            if action["kind"] == "half":
                pos["tp_stage"] = 1
            if not pos["qty"]:
                break
    mark = float(selected.iloc[-1].close)
    received = sum(leg["price"]*leg["qty"] for leg in legs)
    credits = sum(fees._sell_credit(leg["price"], leg["qty"], entry.code) for leg in legs)
    basis = cost*qty
    gross = received + pos["qty"]*mark - basis
    net = credits + pos["qty"]*mark - fees._buy_outlay(cost, qty)
    if sum(leg["qty"] for leg in legs) + pos["qty"] != qty:
        raise AssertionError("quantity conservation")
    return dict(mode=mode, code=entry.code, name=entry.name, buy_time=str(entry.ts), buy_px=cost,
        buy_qty=qty, buy_basis=basis, remaining=pos["qty"], legs=len(legs),
        last_exit=legs[-1]["time"] if legs else None, gross_pnl=round(gross, 2), net_pnl=round(net, 2),
        return_on_entry_cost_pct=round(gross/basis*100, 4), sell_legs=legs)


def run(source, reference, out, end):
    meta = json.loads((reference / "result.json").read_text())
    coverage = json.loads((source / "coverage.json").read_text())
    if coverage.get("failures"):
        raise ValueError("Input source reports coverage failures")
    entries = pd.read_csv(reference / "trades.csv", dtype={"code": str})
    entries = entries[entries.side == "buy"]
    rows, legs, provenance = [], [], []
    for entry in entries.itertuples():
        sina = ("sh" if entry.code.startswith("6") else "sz") + entry.code
        path = source / "minutes" / f"{sina}.parquet"
        daily_path = ROOT / "data_cache" / f"{sina}_daily_qfq.parquet"
        bars = pd.read_parquet(path).copy()
        bars["ts"] = pd.to_datetime(bars.ts).dt.tz_localize(None)
        bars = bars.sort_values("ts")
        if bars.ts.duplicated().any():
            raise ValueError(f"Duplicate minutes: {sina}")
        daily = pd.read_parquet(daily_path).copy()
        daily["date"] = pd.to_datetime(daily.date).dt.tz_localize(None)
        daily = daily.sort_values("date")
        for mode in ("minute_ohlc", "minute_close_proxy"):
            result = simulate(entry, bars, daily, mode=mode, end=end)
            legs.extend(dict(code=entry.code, buy_time=str(entry.ts), mode=mode, **leg) for leg in result.pop("sell_legs"))
            rows.append(result)
        for file in (path, daily_path):
            provenance.append(dict(path=str(file.relative_to(ROOT)), sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
    totals = {}
    for mode in ("minute_ohlc", "minute_close_proxy"):
        chosen = [r for r in rows if r["mode"] == mode]
        totals[mode] = dict(cycles=len(chosen), entry_cost=sum(r["buy_basis"] for r in chosen),
            gross_pnl=round(sum(r["gross_pnl"] for r in chosen), 2),
            net_pnl=round(sum(r["net_pnl"] for r in chosen), 2),
            remaining_symbols=sum(r["remaining"] > 0 for r in chosen))
    result = dict(end=end, totals=totals, fixed_entries=len(entries), comparison="fixed_entries_exit_sensitivity_only",
        live_tick_backtest_supported=False, threshold_fit_end=meta.get("threshold_fit_end"),
        caveats=["Minute-close observations are proxies, not recorded live ticks.",
            "Entry times/quantities are fixed from the minute reference; no cash/slot reallocation is simulated.",
            "Entry minute is excluded because pre/post-entry extremes cannot be separated.",
            "Opening protection is aligned for comparison; minute labels do not prove timely opening quotes.",
            "Thresholds overlap evaluation dates; frozen present-day pool has selection bias.",
            "Totals are sums of fixed-entry cycle PnL, NOT portfolio returns or evidence of superiority."],
        sources=provenance, quantity_conservation_verified=True)
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    pd.DataFrame(rows).to_csv(out / "cycles.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(legs).to_csv(out / "exits.csv", index=False, encoding="utf-8-sig")
    print(json.dumps({k: result[k] for k in ("fixed_entries", "totals", "comparison")}, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    base = Path(__file__).parent
    parser.add_argument("--source", type=Path, default=base / "review_2026-10-01_2026-10-14_intraday_141558")
    parser.add_argument("--reference", type=Path, default=base / "factor29_audit_20261015")
    parser.add_argument("--out", type=Path, default=base / "quote_exit_comparison_20261015")
    parser.add_argument("--end", default="2026-10-13")
    args = parser.parse_args()
    run(args.source.resolve(), args.reference.resolve(), args.out.resolve(), args.end)
