"""赛腾股份回测 CLI。"""

from __future__ import annotations

from pathlib import Path

from run import PRESETS, run_backtest_cli

if __name__ == "__main__":
    run_backtest_cli(
        PRESETS["saiteng"],
        save_monthly=True,
        monthly_csv=Path(__file__).with_name("赛腾股份_monthly.csv"),
    )
