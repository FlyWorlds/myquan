"""Date-bounded Strategy16 portfolio replay with inspectable accounting."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.strategy1_pool_1m import run as engine
from holdingStocks.watch_config import (
    DEFAULT_ACCOUNT_TOTAL, MAX_BUYS_PER_DAY, MAX_PORTFOLIO_SLOTS,
    RESERVE_EMPTY_SLOTS, SLOT_WEIGHT,
)
from strategy.minute import pull_akshare_1m
from strategy.pullback_wave_stop import DEFAULT_PULLBACK_PCT


def add_intraday_daily(daily: pd.DataFrame, minutes: pd.DataFrame, session: str) -> pd.DataFrame:
    bars = minutes[minutes["ts"].dt.strftime("%Y-%m-%d") == session]
    if bars.empty:
        raise ValueError(f"{session}: no intraday bars")
    row = {"date": pd.Timestamp(session), "open": float(bars.iloc[0]["open"]),
           "high": float(bars["high"].max()), "low": float(bars["low"].min()),
           "close": float(bars.iloc[-1]["close"])}
    prior = daily[daily["date"].dt.strftime("%Y-%m-%d") < session]
    return pd.concat([prior, pd.DataFrame([row])], ignore_index=True)


def load_stock(w: dict, start: str, end: str, out: Path, offline: bool,
               cutoff: pd.Timestamp | None = None) -> tuple[dict, dict]:
    sina = w["sina"]
    path = out / "minutes" / f"{sina}.parquet"
    if offline:
        minutes = pd.read_parquet(path)
    else:
        minutes = pull_akshare_1m(em_symbol=w["code"], sina_symbol=sina, adjust="", retries=1)
    if minutes.empty:
        raise ValueError(f"{sina}: no minute data")
    minutes = minutes.copy()
    ts = pd.to_datetime(minutes["ts"])
    if ts.dt.tz is not None:
        ts = ts.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    minutes["ts"] = ts
    minutes = minutes[(ts >= pd.Timestamp(start)) & (ts < pd.Timestamp(end) + pd.Timedelta(days=1))]
    if cutoff is not None:
        minutes = minutes[minutes["ts"] < cutoff.floor("min")]
    minutes = minutes.dropna(subset=["ts", "open", "high", "low", "close"])
    minutes = minutes.sort_values("ts").drop_duplicates("ts", keep="last")
    daily = pd.read_parquet(ROOT / "data_cache" / f"{sina}_daily_qfq.parquet")
    dates = pd.to_datetime(daily["date"])
    if dates.dt.tz is not None:
        dates = dates.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    daily["date"] = dates
    daily = daily[dates < pd.Timestamp(end) + pd.Timedelta(days=1)].copy()
    expected = sorted(set(daily.loc[daily["date"] >= pd.Timestamp(start), "date"].dt.strftime("%Y-%m-%d")))
    counts = minutes.groupby(minutes["ts"].dt.strftime("%Y-%m-%d")).size().to_dict()
    missing = sorted(set(expected) - set(counts))
    short = {day: int(n) for day, n in counts.items() if n < 230 and not (cutoff is not None and day == end)}
    if missing or short or not expected:
        raise ValueError(f"{sina}: incomplete coverage; missing={missing}, short={short}")
    # Daily filters and unadjusted minutes must use the same price scale.
    conflicts = []
    for day, bars in minutes.groupby(minutes["ts"].dt.strftime("%Y-%m-%d")):
        if cutoff is not None and day == end:
            continue
        dr = daily[daily["date"].dt.strftime("%Y-%m-%d") == day]
        if not dr.empty:
            close = float(dr.iloc[-1]["close"])
            actual = float(bars.iloc[-1]["close"])
            if abs(close - actual) > max(0.02, close * 0.002):
                conflicts.append(day)
    if conflicts:
        raise ValueError(f"{sina}: daily/minute close price conflict on {conflicts}")
    if cutoff is not None:
        today = minutes[minutes["ts"].dt.strftime("%Y-%m-%d") == end]
        if today.empty or today["ts"].min() > pd.Timestamp(end) + pd.Timedelta(hours=9, minutes=35):
            raise ValueError(f"{sina}: missing session opening minutes")
        if today["ts"].max() < cutoff.floor("min") - pd.Timedelta(minutes=5):
            raise ValueError(f"{sina}: stale intraday minutes")
        daily = add_intraday_daily(daily, minutes, end)
    if not offline:
        path.parent.mkdir(parents=True, exist_ok=True)
        minutes.to_parquet(path, index=False)
    stock = {"code": w["code"], "name": w["name"], "entry_pct": float(w["entry_pct"]),
             "pullback_pct": float(DEFAULT_PULLBACK_PCT), "daily": daily, "minutes": minutes}
    coverage = {"code": w["code"], "name": w["name"], "days": len(counts),
                "first_ts": str(minutes["ts"].min()), "last_ts": str(minutes["ts"].max()),
                "bars_by_day": counts, "entry_pct": stock["entry_pct"]}
    return stock, coverage


def reconcile(port: dict) -> tuple[list[dict], dict]:
    active: dict[str, dict] = {}
    cycles = []
    buy_cash = sell_cash = gross_realized = 0.0
    for t in port["trades"]:
        code, qty, px = t["code"], int(t["shares"]), float(t["px"])
        if t["side"] == "buy":
            if code in active:
                raise ValueError(f"duplicate active buy: {code}")
            spent = engine._buy_outlay(px, qty)
            buy_cash += spent
            cycle = {"code": code, "name": t["name"], "buy_time": t["ts"], "buy_px": px,
                     "buy_qty": qty, "buy_cost": px * qty, "buy_cash": spent,
                     "sold_qty": 0, "sell_legs": 0, "sell_amount": 0.0,
                     "sell_cash": 0.0, "remaining_qty": qty, "last_sell_time": None}
            active[code] = cycle
            cycles.append(cycle)
        elif t["side"] == "sell":
            cycle = active.get(code)
            if cycle is None or qty > cycle["remaining_qty"]:
                raise ValueError(f"sell exceeds available position: {t}")
            proceeds = engine._sell_credit(px, qty, code)
            sell_cash += proceeds
            gross_realized += qty * (px - cycle["buy_px"])
            cycle["sold_qty"] += qty
            cycle["sell_legs"] += 1
            cycle["sell_amount"] += px * qty
            cycle["sell_cash"] += proceeds
            cycle["remaining_qty"] -= qty
            cycle["last_sell_time"] = t["ts"]
            if not cycle["remaining_qty"]:
                del active[code]
    marks = {p["code"]: p for p in port["open_positions"]}
    floating = market_value = 0.0
    for cycle in cycles:
        qty = cycle["remaining_qty"]
        if qty:
            p = marks[cycle["code"]]
            if qty != int(p["shares"]):
                raise ValueError("open share quantity mismatch")
            mark = float(p["last_px"])
            value = qty * mark
            floating += qty * (mark - cycle["buy_px"])
            market_value += value
        else:
            mark, value = None, 0.0
        cycle["last_px"] = mark
        cycle["gross_pnl"] = round(cycle["sell_amount"] + value - cycle["buy_cost"], 2)
        cycle["net_pnl"] = round(cycle["sell_cash"] + value - cycle["buy_cash"], 2)
        cycle["gross_return_pct"] = round(cycle["gross_pnl"] / cycle["buy_cost"] * 100, 2)
        cycle["net_return_pct"] = round(cycle["net_pnl"] / cycle["buy_cash"] * 100, 2)
    initial = float(port["summary"]["initial_cash"])
    cash = initial - buy_cash + sell_cash
    equity = cash + market_value
    if abs(equity - float(port["summary"]["final_equity"])) > 0.02:
        raise ValueError(f"cash/equity reconciliation failed: {equity}")
    net = equity - initial
    if abs(sum(c["net_pnl"] for c in cycles) - net) > 0.02 * max(1, len(cycles)):
        raise ValueError("trade cycle profit reconciliation failed")
    return cycles, {"net_profit": round(net, 2), "gross_realized": round(gross_realized, 2),
                    "gross_floating": round(floating, 2),
                    "fees_and_slippage": round(gross_realized + floating - net, 2),
                    "cash": round(cash, 2), "market_value": round(market_value, 2),
                    "closed_cycles": sum(c["remaining_qty"] == 0 for c in cycles),
                    "accounting_verified": True}


def simulate_equal_weight_pool(stocks: list[dict]) -> tuple[dict, list[dict]]:
    """Independent equal-capital sleeves; cash is not transferred across stocks."""
    initial = float(DEFAULT_ACCOUNT_TOTAL)
    capital = initial / len(stocks)
    sleeves, constituents = [], []
    for stock in stocks:
        sleeve = engine.simulate_portfolio_3slots(
            [stock], days=1000, max_slots=1, initial_cash=capital,
            slot_weight=1.0, max_buys_per_day=1, reserve_empty=0,
            buy_mode=engine.BUY_MODE_DEFAULT,
        )
        _, accounting = reconcile(sleeve)
        sleeves.append(sleeve)
        constituents.append({"code": stock["code"], "name": stock["name"],
                             "initial_cash": capital, "final_equity": sleeve["summary"]["final_equity"],
                             "return_pct": sleeve["summary"]["return_pct"],
                             "n_buys": sleeve["summary"]["n_buys"],
                             "n_sells": sleeve["summary"]["n_sells"],
                             "n_open": sleeve["summary"]["n_open"], **accounting})
        print(f"SLEEVE {stock['code']} {stock['name']} {sleeve['summary']['return_pct']}%", flush=True)
    calendar = sleeves[0]["summary"]["calendar"]
    if any(s["summary"]["calendar"] != calendar for s in sleeves):
        raise ValueError("equal-weight sleeves have different session calendars")
    trades = sorted([t for s in sleeves for t in s["trades"]], key=lambda t: (t["ts"], t["code"]))
    opened = [p for s in sleeves for p in s["open_positions"]]
    equity = []
    peak, max_dd = initial, 0.0
    for day in calendar:
        rows = [next(e for e in s["equity"] if e["date"] == day) for s in sleeves]
        # Rebuild cash from fills to avoid accumulating rounded sleeve cash.
        fills = [t for t in trades if t["date"] <= day]
        cash = initial + sum(engine._sell_credit(t["px"], t["shares"], t["code"])
                             if t["side"] == "sell" else -engine._buy_outlay(t["px"], t["shares"])
                             for t in fills)
        value = sum(e["equity"] - e["cash"] for e in rows)
        if day == calendar[-1]:
            value = sum(p["last_px"] * p["shares"] for p in opened)
        eq = cash + value
        peak = max(peak, eq)
        max_dd = min(max_dd, eq / peak - 1)
        equity.append({"date": day, "equity": round(eq, 2), "cash": round(cash, 2),
                       "n_pos": sum(e["n_pos"] for e in rows),
                       "codes": ",".join(sorted(c for e in rows for c in e["codes"].split(",") if c)),
                       "ret_pct": round((eq / initial - 1) * 100, 2)})
    ps = {"calendar": calendar, "window_days": len(calendar), "initial_cash": initial,
          "final_equity": equity[-1]["equity"], "return_pct": equity[-1]["ret_pct"],
          "max_dd_pct": round(max_dd * 100, 2), "n_buys": sum(t["side"] == "buy" for t in trades),
          "n_sells": sum(t["side"] == "sell" for t in trades), "n_open": len(opened),
          "allocation": "equal_initial_capital_independent_sleeves",
          "max_slots": len(stocks), "slot_weight": 1 / len(stocks),
          "max_buys_per_day": len(stocks), "cash_per_symbol": capital}
    return {"summary": ps, "trades": trades, "equity": equity, "open_positions": opened,
            "skipped_buys": [t for s in sleeves for t in s["skipped_buys"]]}, constituents


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--intraday", action="store_true", help="Include today's completed minute bars")
    ap.add_argument("--as-of", help="Shanghai cutoff timestamp; also identifies an offline intraday run")
    ap.add_argument("--all-pool", action="store_true", help="Equal-capital independent sleeves for every pool stock")
    args = ap.parse_args()
    start, end = str(pd.Timestamp(args.start).date()), str(pd.Timestamp(args.end).date())
    now = pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None)
    cutoff = pd.Timestamp(args.as_of) if args.as_of else now
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_convert("Asia/Shanghai").tz_localize(None)
    if cutoff > now:
        raise SystemExit("The cutoff cannot be in the future.")
    if args.intraday and (end != str(now.date()) or cutoff.date() != now.date()):
        raise SystemExit("Intraday end and cutoff must be today's Shanghai date.")
    if start > end or (not args.intraday and pd.Timestamp(end).date() >= now.date()):
        raise SystemExit("Use an ordered interval ending on a completed day.")
    if args.offline and args.intraday and not args.as_of:
        raise SystemExit("Offline intraday runs require the original --as-of timestamp.")
    suffix = f"_intraday_{cutoff.strftime('%H%M%S')}" if args.intraday else ""
    data_dir = Path(__file__).resolve().parent / f"review_{start}_{end}{suffix}"
    out = data_dir.with_name(data_dir.name + "_all_pool") if args.all_pool else data_dir
    out.mkdir(parents=True, exist_ok=True)
    pool = engine._load_pool(engine.POOL_STRATEGY16)
    socket.setdefaulttimeout(15)
    payload, coverage, failures = {}, {}, []
    # Initialize the provider's native JS runtime before worker threads use it.
    if not args.offline:
        w = pool[0]
        stock, cov = load_stock(w, start, end, data_dir, False, cutoff if args.intraday else None)
        payload[w["code"]], coverage[w["code"]] = stock, cov
        print(f"OK {w['code']} {w['name']} {cov['bars_by_day']}", flush=True)
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(load_stock, w, start, end, data_dir, args.offline,
                                   cutoff if args.intraday else None): w for w in pool
                   if w["code"] not in payload}
        for future in as_completed(futures):
            w = futures[future]
            try:
                stock, cov = future.result()
                payload[w["code"]], coverage[w["code"]] = stock, cov
                print(f"OK {w['code']} {w['name']} {cov['bars_by_day']}", flush=True)
            except Exception as exc:
                failures.append({"code": w["code"], "error": str(exc)})
                print(f"FAILED {w['code']} {exc}", flush=True)
    (out / "coverage.json").write_text(json.dumps({"coverage": list(coverage.values()), "failures": failures}, ensure_ascii=False, indent=2), encoding="utf-8")
    if failures:
        raise SystemExit("Incomplete inputs; no portfolio return reported. See coverage.json.")
    common_cutoff = None
    if args.intraday:
        common_cutoff = min(s["minutes"]["ts"].max() for s in payload.values())
        for code, stock in payload.items():
            stock["minutes"] = stock["minutes"][stock["minutes"]["ts"] <= common_cutoff].copy()
            stock["daily"] = add_intraday_daily(stock["daily"], stock["minutes"], end)
            coverage[code]["replay_cutoff"] = str(common_cutoff)
        (out / "coverage.json").write_text(json.dumps({"coverage": list(coverage.values()), "failures": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    # Keep the original pool order for deterministic ties between minute signals.
    stocks = [payload[w["code"]] for w in pool]
    constituents = []
    if args.all_pool:
        port, constituents = simulate_equal_weight_pool(stocks)
    else:
        port = engine.simulate_portfolio_3slots(
            stocks, days=1000, max_slots=MAX_PORTFOLIO_SLOTS, initial_cash=DEFAULT_ACCOUNT_TOTAL,
            slot_weight=SLOT_WEIGHT, max_buys_per_day=MAX_BUYS_PER_DAY,
            reserve_empty=RESERVE_EMPTY_SLOTS, buy_mode=engine.BUY_MODE_DEFAULT,
        )
    cycles, accounting = reconcile(port)
    thrs = json.loads((Path(__file__).resolve().parent / "thr_2026.json").read_text())
    result = {"requested_start": start, "requested_end": end, "pool_size": len(pool),
              "threshold_fit_end": thrs.get("fit_end"), "accounting": accounting, "portfolio": port,
              "intraday": bool(args.intraday), "requested_cutoff": str(cutoff) if args.intraday else None,
              "replay_cutoff": str(common_cutoff) if common_cutoff is not None else None}
    result["all_pool"] = bool(args.all_pool)
    result["constituents"] = constituents
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, rows in (("trades", port["trades"]), ("equity", port["equity"]),
                       ("cycles", cycles), ("skipped_buys", port["skipped_buys"])):
        pd.DataFrame(rows).to_csv(out / f"{name}.csv", index=False, encoding="utf-8-sig")
    if constituents:
        pd.DataFrame(constituents).to_csv(out / "constituents.csv", index=False, encoding="utf-8-sig")
    ps = port["summary"]
    lines = ["# 策略16 · 10月区间回测", "",
             f"区间：{start} 至 {end}；实际交易日：{', '.join(ps['calendar'])}。",
             f"当前冻结池 {len(pool)} 只，初始资金 {DEFAULT_ACCOUNT_TOTAL:,.2f} 元，空仓开始。",
             (f"全池等权独立资金：每只初始 {DEFAULT_ACCOUNT_TOTAL / len(pool):,.2f} 元（1/{len(pool)}）；信号买卖，无5槽/日新增2只限制。保留100股整手，闲置资金保留现金，不在股票间调拨。"
              if args.all_pool else f"最多 {MAX_PORTFOLIO_SLOTS} 只；单票目标 {SLOT_WEIGHT:.0%}；日新增最多 {MAX_BUYS_PER_DAY} 只。"),
             "买卖使用项目现有1分钟组合回放引擎，T+1，因子26分批止盈和止损；扣佣金、杂费、印花税及滑点。", "",
             f"共同分钟截止：{common_cutoff}（上海时间，盘中估值，未收盘）" if args.intraday else "仅使用完整交易日。", "",
             "| 指标 | 结果 |", "|---|---:|",
             f"| 期末权益 | {ps['final_equity']:,.2f} 元 |",
             f"| 净盈利 | {accounting['net_profit']:,.2f} 元 |",
             f"| 净收益率 | {ps['return_pct']:.2f}% |",
             f"| 日末/截止时点最大回撤 | {ps['max_dd_pct']:.2f}% |",
             f"| 已实现毛盈亏 | {accounting['gross_realized']:,.2f} 元 |",
             f"| 持仓毛浮盈亏 | {accounting['gross_floating']:,.2f} 元 |",
             f"| 费用与滑点合计 | {accounting['fees_and_slippage']:,.2f} 元 |",
             f"| 买入次数 / 卖出分腿数 | {ps['n_buys']} / {ps['n_sells']} |",
             f"| 完整平仓回合 / 期末持仓 | {accounting['closed_cycles']} / {ps['n_open']} |", "",
             "## 日末/截止时点权益", "", "| 日期 | 权益 | 累计收益率 | 持仓 |", "|---|---:|---:|---|"]
    for e in port["equity"]:
        lines.append(f"| {e['date']} | {e['equity']:,.2f} | {e['ret_pct']:.2f}% | {e['codes'] or '-'} |")
    if constituents:
        lines += ["", "## 全池单票贡献", "", "| 代码 | 名称 | 净盈亏 | 资金收益率 | 买入次数 | 期末持仓 |",
                  "|---|---|---:|---:|---:|---:|"]
        for c in constituents:
            lines.append(f"| {c['code']} | {c['name']} | {c['net_profit']:,.2f} | {c['return_pct']:.2f}% | {c['n_buys']} | {c['n_open']} |")
    lines += ["", "## 核算与限制", "",
              "现金收支、期末持仓市值、整笔净利润与账户权益差额已逐项对平。cycles.csv 按原始买入成本合并分批卖出；卖出分腿数不作为完整交易回合数。",
              f"阈值拟合截止 {thrs.get('fit_end')}，与本区间重叠。这是当前参数的样本内复算，不是样本外绩效。",
              "未导入9月隔夜仓；不是纸面账户10月交割单的真实收益。固定当前池，未重建每天的历史选股池。",
              "1分钟OHLC不能还原真实tick顺序；本引擎按其分钟成交规则处理，不含因子29竞价路径。数据不足时终止，不用日线冒充分钟回测。",
              "分钟源存在少量稀疏记录，逐股逐日根数见 coverage.json；未补造缺失分钟。",
             "10月尚未结束；今天使用已完成分钟估值，不是今日收盘收益。" if args.intraday else "10月尚未结束，仅涵盖指定已完成交易日。", ""]
    (out / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"summary": ps, "accounting": accounting, "report": str(out / "REPORT.md")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
