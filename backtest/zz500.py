"""中证500 ETF 回测 CLI。"""

from __future__ import annotations

from run import PRESETS, run_backtest_cli

if __name__ == "__main__":
    run_backtest_cli(PRESETS["zz500"])
