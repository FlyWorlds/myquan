"""协鑫能科回测 CLI — 配置见 strategy.config.XIEXINNENGKE。"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy import XIEXINNENGKE, STRATEGY_RULES, run_open_break

CFG = replace(
    XIEXINNENGKE,
    min1_cache=Path(__file__).with_name(f"{XIEXINNENGKE.symbol}_1m_qfq.parquet"),
    report_path=Path(__file__).with_name(f"{XIEXINNENGKE.symbol_name}_report.html"),
)


def main(
    *,
    show_report: bool = True,
    gap945_mode: str = XIEXINNENGKE.gap945_exit_mode,
) -> None:
    cfg = replace(CFG, gap945_exit_mode=gap945_mode)
    run_open_break(cfg, show_report=show_report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"{CFG.symbol_name} 开盘±{CFG.threshold_pct*100:.1f}% 策略回测"
    )
    parser.add_argument("--no-open", action="store_true", help="不自动打开 HTML")
    parser.add_argument("--rules", action="store_true", help="打印策略规则")
    parser.add_argument(
        "--gap945-mode",
        choices=("1m", "5m"),
        default=CFG.gap945_exit_mode,
        help="945 卖价：1m 或 5m",
    )
    args = parser.parse_args()
    if args.rules:
        print(STRATEGY_RULES.strip())
        raise SystemExit(0)
    main(show_report=not args.no_open, gap945_mode=args.gap945_mode)
