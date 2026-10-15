"""Read-only single-day condition-order replay. Minute ties are not tick ordering."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "holdingStocks"))
import index as watch
from strategy.minute import standardize_minute_1m
from strategy.factors.factor29 import signal as auction_signal
from strategy.exit_rules.overnight_open_protect import evaluate_overnight_open_protect
from strategy.open_break import cannot_buy_limit_up

SINA_MINUTE_URL = "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData"


def get_json(url):
    with build_opener(ProxyHandler({})).open(url, timeout=5) as response:
        return json.load(response)


def minutes_for(sina: str, day: str, cutoff: pd.Timestamp, out: Path, offline: bool):
    path = out / "minutes" / f"{sina}.parquet"
    if offline:
        frame = pd.read_parquet(path)
    else:
        response = requests.get(SINA_MINUTE_URL, params=dict(symbol=sina, scale="1", ma="no", datalen="1023"),
                                headers={"Referer": "https://finance.sina.com.cn"}, timeout=(3, 8))
        response.raise_for_status()
        _, marker, payload = response.text.partition("=(")
        if not marker:
            raise ValueError("Unexpected Sina JSONP response")
        raw, _ = json.JSONDecoder().raw_decode(payload)
        if not isinstance(raw, list):
            raise ValueError("Expected minute-bar array")
        frame = standardize_minute_1m(pd.DataFrame(raw))
    ts = pd.to_datetime(frame["ts"])
    if ts.dt.tz is not None:
        ts = ts.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    frame["ts"] = ts
    frame = frame[(ts.dt.strftime("%Y-%m-%d") == day) & (ts < cutoff.floor("min"))]
    frame = frame.sort_values("ts").drop_duplicates("ts", keep="last").copy()
    if frame.empty or frame["ts"].min() > pd.Timestamp(day + " 09:31:00"):
        raise ValueError("Opening minute coverage missing")
    if frame["ts"].max() < cutoff.floor("min") - pd.Timedelta(minutes=3):
        raise ValueError("Minute feed stale relative to cutoff")
    if not offline:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
    return frame


def first_touch(bars: pd.DataFrame, *, price: float, official_open: float, prev_close: float,
                limit_pct: float, tick: float, close_proxy: bool = False):
    hi = lo = official_open
    for bar in bars.itertuples():
        hi, lo = max(hi, bar.high), min(lo, bar.low)
        if cannot_buy_limit_up(prev_close=prev_close, open_px=official_open, high_px=hi,
                               low_px=lo, close_px=bar.close, limit_up_pct=limit_pct, tick=tick):
            continue
        observed = bar.close if close_proxy else bar.high
        if observed + 1e-12 >= price and bar.low <= price + 1e-12:
            return str(bar.ts)
    return None


def opening_positions(state: dict, day: str):
    positions = copy.deepcopy(state["holdings"]["positions"])
    cash = float(state["holdings"]["account_cash"])
    today = [t for t in state["trades"] if str(t.get("session") or t.get("time") or "")[:10] == day]
    for trade in reversed(today):
        code, qty = trade["code"], int(trade["qty"])
        pos = positions.setdefault(code, {})
        if trade["side"] == "buy":
            pos["qty"] = int(pos.get("qty") or 0) - qty
            if pos["qty"] < 0:
                raise ValueError("Today's quantity chain cannot be reversed")
            cash += float(trade["amount"])
        elif trade["side"] == "sell":
            pos.update(qty=int(pos.get("qty") or 0) + qty, cost=trade["cost"], buy_time=trade.get("buy_time"))
            cash -= float(trade["amount"])
    return {c: p for c, p in positions.items() if int(p.get("qty") or 0) > 0}, cash, today


def run(out: Path, offline: bool, cutoff: pd.Timestamp | None):
    out.mkdir(parents=True, exist_ok=True)
    if offline:
        saved = json.loads((out / "inputs.json").read_text())
        state, snapshot, pool = saved["state"], saved["snapshot"], saved["pool"]
        cutoff = pd.Timestamp(saved["cutoff"])
    else:
        cutoff = cutoff or pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None)
        state = get_json("http://127.0.0.1:8080/api/paper/state")
        raw = get_json("http://127.0.0.1:8765/api/snapshot")
        snapshot = {"updatedAt": raw.get("updatedAt"), "strategy16": raw.get("strategy16", [])}
        from watch_config import strategy_watchlist
        pool = strategy_watchlist()
        (out / "inputs.json").write_text(json.dumps(dict(state=state, snapshot=snapshot, pool=pool,
                                                        cutoff=str(cutoff)), ensure_ascii=False, indent=2))
    day = str(cutoff.date())
    rows = {str(r["代码"]): r for r in snapshot["strategy16"]}
    opening, initial_cash, actual = opening_positions(state, day)
    frames, errors = {}, []
    with ThreadPoolExecutor(max_workers=4) as executor:
        jobs = {executor.submit(minutes_for, w["sina"], day, cutoff, out, offline): w for w in pool}
        for future in as_completed(jobs):
            w = jobs[future]
            try:
                frames[w["code"]] = future.result()
                print(f"OK {w['code']} {len(frames[w['code']])} bars", flush=True)
            except Exception as exc:
                errors.append(dict(code=w["code"], error=str(exc)))
    (out / "coverage.json").write_text(json.dumps(dict(cutoff=str(cutoff), failures=errors,
        rows={c: dict(count=len(f), first=str(f['ts'].min()), last=str(f['ts'].max())) for c,f in frames.items()}), ensure_ascii=False, indent=2))
    if errors:
        raise ValueError("Incomplete pool data; no claim about the earliest two stocks is allowed")
    common = min(f["ts"].max() for f in frames.values())
    exits = []
    for code, pos in opening.items():
        row = rows.get(code)
        if not row:
            raise ValueError(f"Opening holding {code} absent from snapshot")
        decision = evaluate_overnight_open_protect(dict(cost=pos["cost"], open_px=row["开盘"],
            prev_close=row["昨收"], peak_high=pos.get("overnight_peak") or pos.get("peak_high"),
            qty=pos["qty"], buy_time=pos.get("buy_time"), session=day, overnight_high_ok=True))
        fill = next((t for t in actual if t["code"] == code and t["side"] == "sell"), None)
        # Retain the production rule's decision evidence, rather than running another exit algorithm.
        details = decision.to_dict() if hasattr(decision, "to_dict") else vars(decision)
        exits.append(dict(code=code, name=row["名称"], cost=pos["cost"], qty=pos["qty"],
                          open=row["开盘"], prior_peak=pos.get("overnight_peak") or pos.get("peak_high"),
                          decision=details, actual_fill=fill))
    candidates = []
    from condition_buy import auction_entry_blocked
    for w in pool:
        code, row = w["code"], rows.get(w["code"])
        if not row:
            raise ValueError(f"{code}: row missing")
        daily_path = ROOT / "data_cache" / f"{w['sina']}_daily_qfq.parquet"
        daily = pd.read_parquet(daily_path)
        entry, tick = float(row.get("entryPct") or watch._watch_pct(w)), watch._watch_tick(w)
        gate, gate_label, shape = watch._entry_gate_detail(*watch._prev_bars_from_daily(daily, day),
            entry_pct=entry, tick=tick, prev_entry_mode=str(w.get("prev_entry_mode") or "yin_or_small_yang"))
        price = watch.official_buy_trigger(row["开盘"], entry_pct=entry, tick=tick)
        bars = frames[code][frames[code]["ts"] <= common]
        first = first_touch(bars, price=price, official_open=row["开盘"], prev_close=row["昨收"],
                            limit_pct=watch._watch_limit_down_pct(w), tick=tick) if gate else None
        blocked = auction_entry_blocked(row["开盘"], row["昨收"], limit_up_pct=watch._watch_limit_down_pct(w))
        proxy = first_touch(bars, price=price, official_open=row["开盘"], prev_close=row["昨收"],
            limit_pct=watch._watch_limit_down_pct(w), tick=tick, close_proxy=True) if gate and not blocked else None
        was_held = code in opening
        sold = next((t for t in actual if t["code"] == code and t["side"] == "sell"), None)
        may_rebuy = watch.overnight_gap_rebuy_allowed(state["holdings"].get("realized_today", {}).get(code), session=day)
        if was_held and not (sold and may_rebuy):
            first = None
            proxy = None
        armed = day + (" 09:30:00" if was_held else " 09:25:00")
        f29 = auction_signal(baseline_px=row.get("竞价基准"), auction_high=row.get("竞价最高"),
                             auction_low=row.get("竞价最低"), threshold_pct=entry, tick=tick)
        auction_ok = gate and not blocked and not was_held and bool(f29.get("hit_buy"))
        candidates.append(dict(code=code, name=row["名称"], gate_ok=gate, gate=gate_label, shape=shape,
            open=row["开盘"], threshold_pct=entry, order_price=price, armed_at_assumption=armed,
            first_minute_touch=first, auction_signal=auction_ok, auction_price=row["开盘"] if auction_ok else None,
            quote_close_proxy_first_touch=proxy, auction_near_limit_blocked=blocked,
            previously_held=was_held, rebuy_allowed=may_rebuy, actual_buy=any(t["code"] == code and t["side"] == "buy" for t in actual)))
    ranked = sorted([c for c in candidates if c["first_minute_touch"]], key=lambda c: (c["first_minute_touch"], c["code"]))
    groups = {}
    for c in ranked:
        groups.setdefault(c["first_minute_touch"], []).append(c["code"])
    for c in ranked:
        c["same_minute_codes"] = ",".join(groups[c["first_minute_touch"]])
        c["order_within_minute_unknown"] = len(groups[c["first_minute_touch"]]) > 1
    from watch_config import MAX_NEW_SYMBOLS_PER_SESSION, MAX_POSITION_SYMBOLS
    sold_codes = {t["code"] for t in actual if t["side"] == "sell" and t.get("after_qty") == 0}
    slots = max(0, int(MAX_POSITION_SYMBOLS) - len(set(opening) - sold_codes))
    limit = min(slots, int(MAX_NEW_SYMBOLS_PER_SESSION))
    normal_picks = ranked[:limit]
    auction_cases = [{**c, "first_minute_touch": day + " 09:30:00", "order_price": c["auction_price"]}
                     for c in candidates if c["auction_signal"]]
    auction_codes = {c["code"] for c in auction_cases}
    combined = sorted(auction_cases + [c for c in ranked if c["code"] not in auction_codes],
                      key=lambda c: (c["first_minute_touch"], c["code"]))[:limit]
    result = dict(session=day, requested_cutoff=str(cutoff), common_completed_minute=str(common),
        pool_size=len(pool), initial_cash_from_reversed_today_fills=initial_cash,
        opening_holdings=opening, actual_trades=actual, exits=exits, candidates=candidates,
        ordinary_breakout_minute_tie_reference=normal_picks,
        quote_close_proxy_reference=sorted([c for c in candidates if c["quote_close_proxy_first_touch"]],
            key=lambda c: (c["quote_close_proxy_first_touch"], c["code"]))[:limit],
        quote_close_proxy_is_not_tick_replay=True,
        retained_recorded_auction_counterfactual=combined,
        max_new_symbols=int(MAX_NEW_SYMBOLS_PER_SESSION), max_positions=int(MAX_POSITION_SYMBOLS),
        first_tie_group=next(iter(groups.values()), []), exact_tick_order_available=False,
        assumptions=["9:25 gates/opens available and orders prepared; not proof of actual order placement.",
            "Minute-close proxy rankings are not historical received-quote order and exclude auction orders.",
            "Ordinary fills use first minute high reaching the price with that price inside the bar; exact tick order unknown.",
            "Same-minute ties use code order for an inspectable reference, not the real-time worker's receipt order.",
            "Recorded auction aggregation supports an idealized retained-auction case, not proof of a timely order/open fill.",
            "Actual opening exits are retained for slot availability; this is a buy/timeline replay, not a full independent exit backtest.",
            "Intraday and retrospective frozen thresholds; not an out-of-sample strategy performance evaluation."])
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    pd.DataFrame(candidates).to_csv(out / "candidates.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(ranked).to_csv(out / "buy_timeline.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(actual).to_csv(out / "actual_trades.csv", index=False, encoding="utf-8-sig")
    print(json.dumps({k: result[k] for k in ("common_completed_minute", "ordinary_breakout_minute_tie_reference",
        "retained_recorded_auction_counterfactual", "first_tie_group", "exits")}, ensure_ascii=False, indent=2, default=str))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    run(args.out.resolve(), args.offline, None)
