#!/usr/bin/env python3
"""策略十二·涨停次日低开（研究，非投资建议）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from strategy.strategies.strategy12.gap_reclaim import run_gap_reclaim_backtest  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="策略十二：昨收涨停次日低开")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()
    run_gap_reclaim_backtest(verbose=not args.quiet)


if __name__ == "__main__":
    main()
