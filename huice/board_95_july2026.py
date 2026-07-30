"""2026年7月 — 9.5%触板战法全市场统计。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy.daban.board_95 import (
    STRATEGY_RULES,
    Board95ScanConfig,
    print_board95_report,
    run_board95_scan,
)

JULY_2026 = Board95ScanConfig(
    start_date="20260701",
    end_date="20260731",
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="9.5%触板 · 主板 · 次日竞价出")
    parser.add_argument("--rules", action="store_true", help="打印规则")
    parser.add_argument("--start", default=JULY_2026.start_date)
    parser.add_argument("--end", default=JULY_2026.end_date)
    parser.add_argument("--max", type=int, default=None, help="限制扫描股票数(调试)")
    args = parser.parse_args()
    if args.rules:
        print(STRATEGY_RULES.strip())
        raise SystemExit(0)

    cfg = Board95ScanConfig(
        start_date=args.start,
        end_date=args.end,
        max_symbols=args.max,
    )
    print(f"拉取主板股票池并扫描 {cfg.start_date}~{cfg.end_date} ...")
    trades = run_board95_scan(cfg)
    print_board95_report(cfg, trades)
