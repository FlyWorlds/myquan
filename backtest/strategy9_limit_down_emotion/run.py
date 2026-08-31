#!/usr/bin/env python3
"""策略九·低开跌停情绪回测 CLI。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from strategy.strategies.strategy9.limit_down_emotion import (  # noqa: E402
    INDEX_SYMBOL,
    run_limit_down_emotion_backtest,
)


def main() -> None:
    p = argparse.ArgumentParser(description="策略九·低开跌停情绪：统计家数并对照大盘涨跌")
    p.add_argument("--start", default="20200101")
    p.add_argument("--end", default=None)
    p.add_argument("--index", default=INDEX_SYMBOL, help="大盘指数代码，默认 sh000001")
    p.add_argument("--rebuild", action="store_true", help="重建情绪缓存")
    p.add_argument("--offline", action="store_true", help="禁用网络（需已有缓存）")
    p.add_argument("--max-stocks", type=int, default=None, help="仅统计宇宙前 N 只（调试/快测）")
    p.add_argument("--workers", type=int, default=8, help="并行拉取日线线程数")
    args = p.parse_args()
    run_limit_down_emotion_backtest(
        start=args.start,
        end=args.end,
        index_symbol=args.index,
        rebuild=args.rebuild,
        allow_network=not args.offline,
        max_stocks=args.max_stocks,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
