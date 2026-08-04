"""赛腾股份回测 CLI — OpenBreak3 开盘±2.5%。"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy import BacktestConfig, STRATEGY_RULES, run_open_break
from strategy.backtest import monthly_returns_df

CFG = replace(
    BacktestConfig(
        symbol="sh603283",
        symbol_name="赛腾股份",
        em_symbol="603283",
        threshold_pct=0.025,
        start_date="20200101",
    ),
    report_path=Path(__file__).with_name("赛腾股份_report.html"),
)

MONTHLY_CSV = Path(__file__).with_name("赛腾股份_monthly.csv")


def main(*, show_report: bool = True) -> None:
    result, daily = run_open_break(CFG, show_report=show_report)
    df = monthly_returns_df(result, daily, initial_cash=CFG.initial_cash)
    if not df.empty:
        df.to_csv(MONTHLY_CSV, index=False, encoding="utf-8-sig")
        print(f"\n分月 CSV: {MONTHLY_CSV}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"{CFG.symbol_name} 开盘±{CFG.threshold_pct * 100:.1f}% 策略回测"
    )
    parser.add_argument("--no-open", action="store_true", help="不自动打开 HTML")
    parser.add_argument("--rules", action="store_true", help="打印策略规则")
    args = parser.parse_args()
    if args.rules:
        print(STRATEGY_RULES.strip())
        raise SystemExit(0)
    main(show_report=not args.no_open)
