"""中证500 ETF 回测 CLI — 配置见 strategy.config.ZZ500_ETF。"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy import ZZ500_ETF, run_open_break

CFG = replace(
    ZZ500_ETF,
    min1_cache=Path(__file__).with_name(f"{ZZ500_ETF.symbol}_1m_qfq.parquet"),
    report_path=Path(__file__).with_name(f"{ZZ500_ETF.symbol_name}_report.html"),
)


def main(*, show_report: bool = True) -> None:
    run_open_break(CFG, show_report=show_report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"{CFG.symbol_name} 开盘±{CFG.threshold_pct*100:.1f}% 策略回测"
    )
    parser.add_argument("--no-open", action="store_true", help="不自动打开 HTML")
    args = parser.parse_args()
    main(show_report=not args.no_open)
