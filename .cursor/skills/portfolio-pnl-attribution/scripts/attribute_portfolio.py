#!/usr/bin/env python3
"""Reconcile realized portfolio returns to security and sector contributions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


def _read(path: str, required: list[str]) -> pd.DataFrame:
    frame = pd.read_csv(path)
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    return frame


def attribute_portfolio(
    positions: pd.DataFrame,
    returns: pd.DataFrame,
    benchmark: Optional[pd.DataFrame] = None,
    fees: Optional[pd.DataFrame] = None,
) -> dict[str, pd.DataFrame | dict]:
    positions = positions.copy()
    returns = returns.copy()
    positions["date"] = pd.to_datetime(positions["date"], errors="raise").dt.normalize()
    returns["date"] = pd.to_datetime(returns["date"], errors="raise").dt.normalize()
    positions["weight"] = pd.to_numeric(positions["weight"], errors="raise")
    returns["asset_return"] = pd.to_numeric(returns["asset_return"], errors="raise")
    if positions.duplicated(["date", "symbol"]).any():
        raise ValueError("positions contains duplicate (date, symbol) keys")
    if returns.duplicated(["date", "symbol"]).any():
        raise ValueError("returns contains duplicate (date, symbol) keys")

    joined = positions.merge(returns, on=["date", "symbol"], how="left", validate="one_to_one")
    missing = joined.loc[joined["asset_return"].isna(), ["date", "symbol"]]
    if not missing.empty:
        keys = [f"{d.date()}:{s}" for d, s in missing.itertuples(index=False)]
        raise ValueError(f"missing same-date returns for {keys[:10]}")
    joined["contribution"] = joined["weight"] * joined["asset_return"]

    daily = joined.groupby("date", as_index=False).agg(
        gross_return=("contribution", "sum"),
        weight_sum=("weight", "sum"),
        security_count=("symbol", "nunique"),
    )
    daily["reconciliation_error"] = daily["gross_return"] - joined.groupby("date")["contribution"].sum().to_numpy()
    daily["fees"] = 0.0
    warnings: list[str] = []
    if fees is not None:
        fees = fees.copy()
        if "date" not in fees.columns or "fee" not in fees.columns:
            raise ValueError("fees must contain date and fee columns")
        fees["date"] = pd.to_datetime(fees["date"], errors="raise").dt.normalize()
        fees["fee"] = pd.to_numeric(fees["fee"], errors="raise")
        if fees.duplicated("date").any():
            raise ValueError("fees contains duplicate dates")
        daily = daily.drop(columns="fees").merge(fees[["date", "fee"]].rename(columns={"fee": "fees"}), on="date", how="left")
        daily["fees"] = daily["fees"].fillna(0.0)
    if (daily["weight_sum"] - 1.0).abs().gt(1e-6).any():
        warnings.append("some daily weights do not sum to one")
    daily["net_return"] = daily["gross_return"] - daily["fees"]
    daily["benchmark_return"] = np.nan
    if benchmark is not None:
        benchmark = benchmark.copy()
        if not {"date", "benchmark_return"}.issubset(benchmark.columns):
            raise ValueError("benchmark must contain date and benchmark_return columns")
        benchmark["date"] = pd.to_datetime(benchmark["date"], errors="raise").dt.normalize()
        benchmark["benchmark_return"] = pd.to_numeric(benchmark["benchmark_return"], errors="raise")
        if benchmark.duplicated("date").any():
            raise ValueError("benchmark contains duplicate dates")
        daily = daily.drop(columns="benchmark_return").merge(benchmark[["date", "benchmark_return"]], on="date", how="left")
    daily["active_return"] = daily["net_return"] - daily["benchmark_return"].fillna(0.0)

    sector = pd.DataFrame(columns=["date", "sector", "sector_contribution"])
    if "sector" in joined.columns:
        sector = joined.groupby(["date", "sector"], as_index=False)["contribution"].sum().rename(columns={"contribution": "sector_contribution"})
    summary = {
        "rows": int(len(joined)),
        "dates": int(daily["date"].nunique()),
        "date_start": daily["date"].min().date().isoformat() if len(daily) else None,
        "date_end": daily["date"].max().date().isoformat() if len(daily) else None,
        "cumulative_gross_return": float((1.0 + daily["gross_return"]).prod() - 1.0),
        "cumulative_net_return": float((1.0 + daily["net_return"]).prod() - 1.0),
        "cumulative_active_return": float((1.0 + daily["active_return"]).prod() - 1.0) if benchmark is not None else None,
        "max_reconciliation_error": float(daily["reconciliation_error"].abs().max()) if len(daily) else 0.0,
        "warnings": warnings,
    }
    return {"security": joined, "sector": sector, "daily": daily, "summary": summary}


def _demo() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    positions = pd.DataFrame({"date": ["2026-01-02", "2026-01-02", "2026-01-03", "2026-01-03"], "symbol": ["AAA", "BBB", "AAA", "BBB"], "weight": [0.6, 0.4, 0.5, 0.5], "sector": ["Tech", "Health", "Tech", "Health"]})
    returns = pd.DataFrame({"date": ["2026-01-02", "2026-01-02", "2026-01-03", "2026-01-03"], "symbol": ["AAA", "BBB", "AAA", "BBB"], "asset_return": [0.01, -0.005, -0.002, 0.008]})
    benchmark = pd.DataFrame({"date": ["2026-01-02", "2026-01-03"], "benchmark_return": [0.003, 0.002]})
    fees = pd.DataFrame({"date": ["2026-01-02", "2026-01-03"], "fee": [0.0002, 0.0001]})
    return positions, returns, benchmark, fees


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positions")
    parser.add_argument("--returns")
    parser.add_argument("--benchmark")
    parser.add_argument("--fees")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    if args.demo:
        positions, returns, benchmark, fees = _demo()
    else:
        if not args.positions or not args.returns:
            parser.error("--positions and --returns are required unless --demo is used")
        positions = _read(args.positions, ["date", "symbol", "weight"])
        returns = _read(args.returns, ["date", "symbol", "asset_return"])
        benchmark = _read(args.benchmark, ["date", "benchmark_return"]) if args.benchmark else None
        fees = _read(args.fees, ["date", "fee"]) if args.fees else None
    result = attribute_portfolio(positions, returns, benchmark, fees)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    result["security"].to_csv(out / "security_attribution.csv", index=False)
    result["sector"].to_csv(out / "sector_attribution.csv", index=False)
    result["daily"].to_csv(out / "daily_attribution.csv", index=False)
    (out / "summary.json").write_text(json.dumps(result["summary"], indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
