"""凯盛科技 — 低开幅度分区 × 收盘阴/阳统计。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy.gap_down_close import GapCloseConfig, run_gap_down_close

CFG = GapCloseConfig(
    symbol="sh600552",
    symbol_name="凯盛科技",
    start_date="20100101",
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="低开幅度 × 收盘阴/阳")
    parser.add_argument("--start", default=CFG.start_date, help="起始 YYYYMMDD")
    parser.add_argument("--by-year", action="store_true", help="按年输出各区间阴/阳")
    parser.add_argument(
        "--down-wave",
        action="store_true",
        help="仅统计下跌波段(MA5<MA10<MA21)",
    )
    parser.add_argument(
        "--max-drop",
        action="store_true",
        help="统计低开阶段最大跌幅",
    )
    parser.add_argument(
        "--years",
        default="2025,2026",
        help="--max-drop 时指定年份，逗号分隔",
    )
    args = parser.parse_args()
    cfg = GapCloseConfig(
        symbol=CFG.symbol,
        symbol_name=CFG.symbol_name,
        start_date=args.start if not args.max_drop else "20200101",
        by_year=args.by_year,
        down_wave_only=args.down_wave,
    )
    if args.max_drop:
        years = [y.strip() for y in args.years.split(",") if y.strip()]
        from strategy.gap_down_close import run_gap_max_drop

        run_gap_max_drop(cfg, years=years)
    else:
        run_gap_down_close(cfg)
