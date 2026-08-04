"""航天电子回测 CLI — 配置见 strategy.config.HANGTIANDIANZI。"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy import HANGTIANDIANZI, STRATEGY_RULES, run_open_break

CFG = replace(
    HANGTIANDIANZI,
    report_path=Path(__file__).with_name(f"{HANGTIANDIANZI.symbol_name}_report.html"),
)


def main(
    *,
    show_report: bool = True,
) -> None:
    run_open_break(CFG, show_report=show_report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"{CFG.symbol_name} 开盘±{CFG.threshold_pct*100:.1f}% 策略回测"
    )
    parser.add_argument("--no-open", action="store_true", help="不自动打开 HTML")
    parser.add_argument("--rules", action="store_true", help="打印策略规则")
    args = parser.parse_args()
    if args.rules:
        print(STRATEGY_RULES.strip())
        raise SystemExit(0)
    main(show_report=not args.no_open)
