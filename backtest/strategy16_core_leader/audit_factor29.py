"""Offline Factor29 evidence audit and Factor26-only reference replay.

Never infer auction strength from the final open or treat absent auction ticks as
no signal. This runner writes research outputs only, not the production account.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.strategy16_core_leader.run_month_review import load_stock, reconcile
from backtest.strategy1_pool_1m import run as engine


def auction_rows(frame: pd.DataFrame) -> int:
    ts = pd.to_datetime(frame["ts"])
    if ts.dt.tz is not None:
        ts = ts.dt.tz_convert("Asia/Shanghai")
    clock = ts.dt.strftime("%H:%M:%S")
    return int(((clock >= "09:20:00") & (clock < "09:25:00")).sum())


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(source: Path, out: Path, start: str, end: str) -> dict:
    original = json.loads((source / "result.json").read_text())
    coverage = json.loads((source / "coverage.json").read_text())
    if coverage.get("failures"):
        raise ValueError("Source replay has missing inputs")
    rows = {str(r["code"]): r for r in coverage["coverage"]}
    pool = engine._load_pool(engine.POOL_STRATEGY16)
    if set(rows) != {str(w["code"]) for w in pool}:
        raise ValueError("Pool changed since the source snapshot; freeze/review the universe first")
    stocks, checks, sources = [], [], []
    for w in pool:
        row = rows[str(w["code"])]
        fixed = dict(w, entry_pct=float(row["entry_pct"]))
        stock, cov = load_stock(fixed, start, end, source, True)
        path = source / "minutes" / f"{w['sina']}.parquet"
        count = auction_rows(stock["minutes"])
        checks.append(dict(cov, auction_rows=count, auction_path_available=False))
        stocks.append(stock)
        for file in (path, ROOT / "data_cache" / f"{w['sina']}_daily_qfq.parquet"):
            sources.append({"path": str(file.relative_to(ROOT)), "sha256": fingerprint(file)})
    config = original["portfolio"]["summary"]
    port = engine.simulate_portfolio_3slots(
        stocks, days=1000, max_slots=config["max_slots"], initial_cash=config["initial_cash"],
        slot_weight=config["slot_weight"], max_buys_per_day=config["max_buys_per_day"],
        reserve_empty=config["reserve_empty"], buy_mode=config["buy_mode"],
        exit_mode=config["exit_mode"],
    )
    cycles, accounting = reconcile(port)
    result = {
        "requested_start": start, "requested_end": end,
        "source_replay": str(source.relative_to(ROOT)), "pool_size": len(stocks),
        "pool_order": [s["code"] for s in stocks],
        "threshold_fit_end": original.get("threshold_fit_end"),
        "threshold_overlap": bool(original.get("threshold_fit_end") and original["threshold_fit_end"] >= start),
        "minute_rows": sum(len(s["minutes"]) for s in stocks),
        "auction_rows": sum(r["auction_rows"] for r in checks),
        "comparable_sessions": 0,
        "comparison_status": "blocked_missing_point_in_time_auction_paths_and_factor29_engine",
        "factor29_on": None,
        "factor26_only_reference": {"summary": port["summary"], "accounting": accounting},
        "coverage": checks, "sources": sources,
        "caveats": [
            "Baseline engine has no Factor29 entry or exit support; no valid on/off delta is produced.",
            "A 09:25/09:30 opening bar cannot reconstruct 09:20-09:24:59 indicative-price paths.",
            "Thresholds overlap the evaluation window; this is not an out-of-sample test.",
            "Reference starts flat, not from the live paper account; no production state is read or changed.",
            "Current frozen universe and threshold choices are held fixed; pool-order minute ties are not tick-order proof.",
        ],
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    for name, data in (("coverage", checks), ("trades", port["trades"]),
                       ("equity", port["equity"]), ("cycles", cycles)):
        pd.DataFrame(data).to_csv(out / f"{name}.csv", index=False, encoding="utf-8-sig")
    print(json.dumps({k: result[k] for k in ("pool_size", "minute_rows", "auction_rows",
        "comparable_sessions", "comparison_status", "factor26_only_reference")}, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).parent / "review_2026-10-01_2026-10-14_intraday_141558")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "factor29_audit_20261015")
    parser.add_argument("--start", default="2026-10-01")
    parser.add_argument("--end", default="2026-10-13")
    args = parser.parse_args()
    if pd.Timestamp(args.start) > pd.Timestamp(args.end):
        parser.error("start must not follow end")
    if pd.Timestamp(args.end).date() >= pd.Timestamp.now(tz="Asia/Shanghai").date():
        parser.error("Use completed sessions only")
    run(args.source.resolve(), args.out.resolve(), args.start, args.end)
