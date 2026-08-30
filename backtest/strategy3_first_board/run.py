#!/usr/bin/env python3
"""策略三·首板晋级回测 CLI（2.5% / 3%）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from strategy.strategies.strategy3.first_board import run_first_board_promotion_backtest  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="策略三·首板晋级回测")
    p.add_argument("--start", default="20200101")
    p.add_argument("--end", default=None)
    p.add_argument(
        "--entry-pcts",
        default="0.025,0.03",
        help="逗号分隔阈值，默认 0.025,0.03",
    )
    p.add_argument("--cash", type=float, default=1_000_000.0)
    p.add_argument("--max-positions", type=int, default=10)
    p.add_argument("--mkt-lu-min", type=int, default=-1, help="T-1 涨停家数下限，-1=不限制")
    p.add_argument("--mkt-lu-max", type=int, default=-1, help="T-1 涨停家数上限，-1=不限制")
    p.add_argument("--mkt-lianban-min", type=int, default=2, help="T-1 连板家数下限，-1=不限制")
    p.add_argument("--mkt-max-height-min", type=int, default=2, help="T-1 最高板下限，-1=不限制")
    p.add_argument("--mkt-max-height-max", type=int, default=5, help="T-1 最高板上限，-1=不限制")
    p.add_argument("--mkt-ladder-score-min", type=int, default=-1, help="T-1 梯度得分下限，-1=不限制")
    p.add_argument("--sentiment-lag", type=int, default=1, help="情绪取晋级日前 N 个交易日")
    p.add_argument(
        "--pool",
        choices=("first_board", "yesterday_lu"),
        default="yesterday_lu",
        help="股池：first_board=首板+gap/量比；yesterday_lu=昨日涨停全池（盯盘口径）",
    )
    p.add_argument("--rebuild", action="store_true")
    args = p.parse_args()
    pcts = tuple(float(x.strip()) for x in args.entry_pcts.split(",") if x.strip())

    def _opt(v: int) -> int | None:
        return None if v < 0 else v

    run_first_board_promotion_backtest(
        start=args.start,
        end=args.end,
        entry_pcts=pcts,
        initial_cash=args.cash,
        max_positions=args.max_positions,
        mkt_lu_min=_opt(args.mkt_lu_min),
        mkt_lu_max=_opt(args.mkt_lu_max),
        mkt_lianban_min=_opt(args.mkt_lianban_min),
        mkt_max_height_min=_opt(args.mkt_max_height_min),
        mkt_max_height_max=_opt(args.mkt_max_height_max),
        mkt_ladder_score_min=_opt(args.mkt_ladder_score_min),
        sentiment_lag=args.sentiment_lag,
        pool_mode=args.pool,
        rebuild_signals=args.rebuild,
    )


if __name__ == "__main__":
    main()
