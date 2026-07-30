"""凯盛科技 — 打板战法回测。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy.daban.config import KAICHENG_DABAN, DaBanConfig
from strategy.daban.rules import STRATEGY_RULES
from strategy.daban.runner import run_daban


def main(cfg: DaBanConfig | None = None) -> None:
    run_daban(cfg or KAICHENG_DABAN, show_report=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="凯盛科技 打板战法回测")
    parser.add_argument("--rules", action="store_true", help="打印策略规则")
    parser.add_argument("--start", default=KAICHENG_DABAN.start_date, help="起始 YYYYMMDD")
    parser.add_argument(
        "--limit-pct",
        type=float,
        default=KAICHENG_DABAN.limit_pct,
        help="涨停幅度，默认 0.10",
    )
    parser.add_argument(
        "--gap-exit",
        type=float,
        default=KAICHENG_DABAN.gap_down_exit_pct,
        help="低开卖出阈值，默认 0.03",
    )
    args = parser.parse_args()
    if args.rules:
        print(STRATEGY_RULES.strip())
        raise SystemExit(0)
    cfg = DaBanConfig(
        symbol=KAICHENG_DABAN.symbol,
        symbol_name=KAICHENG_DABAN.symbol_name,
        em_symbol=KAICHENG_DABAN.em_symbol,
        start_date=args.start,
        limit_pct=args.limit_pct,
        gap_down_exit_pct=args.gap_exit,
    )
    run_daban(cfg)
