"""天通股份回测 CLI — 支持 --threshold 2/2.5/3。"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from run import PRESETS
from strategy import STRATEGY_RULES, run_open_break
from strategy.backtest import monthly_returns_df

DEFAULT_THRESHOLD = 2.5
BASE = PRESETS["tiantong"]


def _artifact_paths(threshold: float) -> tuple[Path, Path]:
    stem = "天通股份" if threshold == DEFAULT_THRESHOLD else f"天通股份_{threshold:g}pct"
    d = Path(__file__).parent
    return d / f"{stem}_report.html", d / f"{stem}_monthly.csv"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"{BASE.symbol_name} OpenBreak3 策略回测")
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--rules", action="store_true")
    parser.add_argument(
        "--threshold",
        type=float,
        choices=(2.0, 2.5, 3.0),
        default=DEFAULT_THRESHOLD,
        help="开盘±阈值 %%（默认 2.5）",
    )
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()
    if args.rules:
        print(STRATEGY_RULES.strip())
        raise SystemExit(0)

    report_path, monthly_csv = _artifact_paths(args.threshold)
    cfg = replace(
        BASE,
        threshold_pct=args.threshold / 100.0,
        report_path=report_path,
    )
    result, daily = run_open_break(
        cfg,
        show_report=not args.no_open,
        force_daily_refresh=bool(args.force_refresh),
    )
    df = monthly_returns_df(result, daily, initial_cash=cfg.initial_cash)
    if not df.empty:
        df.to_csv(monthly_csv, index=False, encoding="utf-8-sig")
        print(f"\n分月 CSV: {monthly_csv}")
