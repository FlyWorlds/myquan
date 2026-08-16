from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from backtest import release_checks, run_backtest
from factor import (
    DEFAULT_DATA_VERSION,
    FACTOR_ID,
    calculate_factor,
    extract_calendar_trade_dates,
    validate_production_output,
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="用 PandaData 固定原始快照构建并验收最终版 A06")
    parser.add_argument("--details", required=True)
    parser.add_argument("--calendar", required=True)
    parser.add_argument("--quotes", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    quotes = pd.read_parquet(args.quotes)
    calendar = pd.read_parquet(args.calendar)
    factor_all = calculate_factor(
        pd.read_parquet(args.details),
        trade_calendar=calendar,
        quotes=quotes,
        data_version=DEFAULT_DATA_VERSION,
        update_time=datetime.now().isoformat(timespec="seconds"),
        dynamic_seat_quality=False,
    )
    start = pd.to_datetime(args.start_date)
    end = pd.to_datetime(args.end_date)
    factor = factor_all.loc[
        (pd.to_datetime(factor_all["trade_date"]) >= start)
        & (pd.to_datetime(factor_all["trade_date"]) <= end)
    ].copy()
    validate_production_output(factor, valid_trade_dates=extract_calendar_trade_dates(calendar))

    standard = run_backtest(factor, quotes, round_trip_cost=0.003)
    stress = run_backtest(factor, quotes, round_trip_cost=0.005)
    extreme = run_backtest(factor, quotes, round_trip_cost=0.010)
    standard_checks = release_checks(standard)
    stress_checks = release_checks(stress)
    release_pass = all(standard_checks.values()) and all(stress_checks.values())
    report = {
        "factor_id": FACTOR_ID,
        "source": "PandaData fixed raw snapshot",
        "data_version": DEFAULT_DATA_VERSION,
        "factor_date_min": factor["trade_date"].min(),
        "factor_date_max": factor["trade_date"].max(),
        "rows": len(factor),
        "release_pass": release_pass,
        "standard_cost_0_003": standard,
        "standard_checks": standard_checks,
        "stress_cost_0_005": stress,
        "stress_checks": stress_checks,
        "extreme_cost_0_010_information_only": extreme,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=2), encoding="utf-8")
    if not release_pass:
        raise RuntimeError(f"最终版未通过发布门槛，报告已写入 {report_path}")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    factor.to_parquet(output, index=False)
    print(f"release_pass: {release_pass}")
    print(f"output: {output}")
    print(f"report: {report_path}")


if __name__ == "__main__":
    main()
