#!/usr/bin/env python3
"""策略八·题材联动回测 CLI。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from strategy.strategies.strategy8.theme_linkage import run_theme_linkage_backtest  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="策略八·题材联动回测")
    p.add_argument("--start", default="20250101")
    p.add_argument("--end", default=None)
    p.add_argument("--entry-pcts", default="0.025,0.03")
    p.add_argument("--cash", type=float, default=1_000_000.0)
    p.add_argument("--max-positions", type=int, default=10)
    p.add_argument("--min-theme-lu", type=int, default=3, help="同题材最少涨停同伴数")
    p.add_argument(
        "--pool",
        choices=("members", "linkage", "lu_theme"),
        default="linkage",
        help="members=热题材全部；linkage=联动（非当日涨停）；lu_theme=当日涨停+同题材",
    )
    p.add_argument("--gap-filter", action="store_true", help="启用因子15低开带过滤")
    p.add_argument("--mkt-lianban-min", type=int, default=2)
    p.add_argument("--mkt-max-height-min", type=int, default=2)
    p.add_argument("--mkt-max-height-max", type=int, default=5)
    p.add_argument("--sentiment-lag", type=int, default=1)
    p.add_argument("--rebuild", action="store_true")
    args = p.parse_args()
    pcts = tuple(float(x.strip()) for x in args.entry_pcts.split(",") if x.strip())

    run_theme_linkage_backtest(
        start=args.start,
        end=args.end,
        entry_pcts=pcts,
        initial_cash=args.cash,
        max_positions=args.max_positions,
        min_theme_lu=args.min_theme_lu,
        pool_mode=args.pool,
        apply_gap_filter=args.gap_filter,
        mkt_lianban_min=args.mkt_lianban_min,
        mkt_max_height_min=args.mkt_max_height_min,
        mkt_max_height_max=args.mkt_max_height_max,
        sentiment_lag=args.sentiment_lag,
        rebuild_signals=args.rebuild,
    )


if __name__ == "__main__":
    main()
