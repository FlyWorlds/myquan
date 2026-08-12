#!/usr/bin/env python3
"""策略四入口：打印/导出累计评分可买 Top20。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

import strategy.strategies  # noqa: F401
from strategy.core.strategy_registry import get_strategy_spec


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="策略四 · 因子1 可买 Top20")
    p.add_argument("--rules", action="store_true")
    p.add_argument("--top-n", type=int, default=None)
    p.add_argument("--score-mode", default=None, help="cum2020|roll12|month")
    args = p.parse_args(argv)

    spec = get_strategy_spec("strategy4")
    if args.rules and spec.print_rules:
        print(spec.print_rules())
        return

    overrides = {}
    if args.top_n is not None:
        overrides["top_n"] = args.top_n
    if args.score_mode is not None:
        overrides["score_mode"] = args.score_mode
    spec.run(**overrides)


if __name__ == "__main__":
    main()
