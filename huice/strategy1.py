"""凯盛科技回测 CLI — 配置见 strategy.config.KAICHENG。"""

from __future__ import annotations

from run import PRESETS, run_backtest_cli

if __name__ == "__main__":
    run_backtest_cli(PRESETS["kaicheng"])
