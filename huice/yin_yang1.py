"""凯盛科技 — 超跌反弹形态统计（次日开盘/最高/收盘 + 历史回测）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy.oversold_bounce import STRATEGY_RULES, ScanConfig, run_scan

CFG = ScanConfig(
    symbol="sh600552",
    symbol_name="凯盛科技",
    start_date="20100101",
)


def main(cfg: ScanConfig | None = None) -> None:
    run_scan(cfg or CFG)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="凯盛科技 超跌反弹形态次日统计")
    parser.add_argument("--rules", action="store_true", help="打印形态规则")
    parser.add_argument(
        "--start",
        default=CFG.start_date,
        help="起始日期 YYYYMMDD（默认 20100101 以覆盖更多历史样本）",
    )
    parser.add_argument(
        "--body-mode",
        choices=("abs", "pct"),
        default="pct",
        help="小实体：pct=实体占开盘%<1(默认); abs=实体<1元",
    )
    args = parser.parse_args()
    if args.rules:
        print(STRATEGY_RULES.strip())
        raise SystemExit(0)
    cfg = ScanConfig(
        symbol=CFG.symbol,
        symbol_name=CFG.symbol_name,
        start_date=args.start,
        body_mode=args.body_mode,
    )
    run_scan(cfg)
