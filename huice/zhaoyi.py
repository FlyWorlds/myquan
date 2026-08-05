"""兆易创新回测 CLI。"""

from __future__ import annotations

from pathlib import Path

from run import PRESETS, run_backtest_cli

if __name__ == "__main__":
    run_backtest_cli(
        PRESETS["zhaoyi"],
        save_monthly=True,
        monthly_csv=Path(__file__).with_name("兆易创新_monthly.csv"),
    )
