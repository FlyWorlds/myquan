"""天通股份回测 CLI — OpenBreak3 开盘±pct。"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy import BacktestConfig, STRATEGY_RULES, run_open_break
from strategy.backtest import monthly_returns_df

BASE_CFG = BacktestConfig(
    symbol="sh600330",
    symbol_name="天通股份",
    em_symbol="600330",
    threshold_pct=0.025,
    start_date="20200101",
)

DEFAULT_THRESHOLD = 2.5


def _artifact_paths(threshold: float) -> tuple[Path, Path]:
    stem = "天通股份" if threshold == DEFAULT_THRESHOLD else f"天通股份_{threshold:g}pct"
    d = Path(__file__).parent
    return d / f"{stem}_report.html", d / f"{stem}_monthly.csv"


def _build_cfg(*, threshold: float) -> BacktestConfig:
    report_path, _ = _artifact_paths(threshold)
    return replace(
        BASE_CFG,
        threshold_pct=threshold / 100.0,
        report_path=report_path,
    )


def main(
    *,
    threshold: float = DEFAULT_THRESHOLD,
    show_report: bool = True,
) -> None:
    cfg = _build_cfg(threshold=threshold)
    _, monthly_csv = _artifact_paths(threshold)
    result, daily = run_open_break(cfg, show_report=show_report)
    df = monthly_returns_df(result, daily, initial_cash=cfg.initial_cash)
    if not df.empty:
        df.to_csv(monthly_csv, index=False, encoding="utf-8-sig")
        print(f"\n分月 CSV: {monthly_csv}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"{BASE_CFG.symbol_name} OpenBreak3 策略回测")
    parser.add_argument("--no-open", action="store_true", help="不自动打开 HTML")
    parser.add_argument("--rules", action="store_true", help="打印策略规则")
    parser.add_argument(
        "--threshold",
        type=float,
        choices=(2.0, 2.5, 3.0),
        default=DEFAULT_THRESHOLD,
        help="开盘±阈值 %%（默认 2.5）",
    )
    args = parser.parse_args()
    if args.rules:
        print(STRATEGY_RULES.strip())
        raise SystemExit(0)
    main(
        threshold=args.threshold,
        show_report=not args.no_open,
    )
