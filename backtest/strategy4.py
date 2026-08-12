#!/usr/bin/env python3
"""策略四入口：roll12 Top3 池 × 池内反转。"""

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
    p = argparse.ArgumentParser(description="策略四 · 因子1 roll12 Top3 × 池内反转")
    p.add_argument("--rules", action="store_true")
    p.add_argument("--picks", action="store_true", help="只打印当前选股")
    p.add_argument("--no-open", action="store_true")
    args = p.parse_args(argv)

    spec = get_strategy_spec("strategy4")
    if args.rules and spec.print_rules:
        print(spec.print_rules())
        return

    out = Path(__file__).resolve().parent / "strategy4_out"
    out.mkdir(parents=True, exist_ok=True)

    if args.picks:
        df = spec.run(picks_only=True)
        print(df.to_string(index=False))
        df.to_csv(out / "current_picks.csv", index=False, encoding="utf-8-sig")
        print(f"写入 {out / 'current_picks.csv'}")
        return

    result = spec.run(verbose=True)
    print("\n摘要:")
    for k in (
        "start",
        "end",
        "total_return_pct",
        "max_drawdown_pct",
        "sharpe",
        "n_buys",
        "score_mode",
        "pool_n",
        "factor",
    ):
        print(f"  {k}: {result.stats.get(k)}")
    if result.yearly is not None and not result.yearly.empty:
        print("\n分年:")
        print(result.yearly.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    result.equity.to_csv(out / "equity.csv", index=False, encoding="utf-8-sig")
    result.yearly.to_csv(out / "yearly.csv", index=False, encoding="utf-8-sig")
    result.pool.to_csv(out / "pool.csv", index=False, encoding="utf-8-sig")
    if not result.picks.empty:
        result.picks.tail(30).to_csv(out / "picks_tail.csv", index=False, encoding="utf-8-sig")
    print(f"\n产物: {out}")


if __name__ == "__main__":
    main()
