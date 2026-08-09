"""因子2 / 策略一叠加回测（推荐直接用 strategy1.py）。

用法:
  python factor2.py
  python factor2.py --add-pct 0.12
  python factor2.py --rules
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from strategy import KAICHENG, get_strategy, run_strategy1  # noqa: E402
from strategy.dd_topup import DEFAULT_ADD_PCT, DEFAULT_LEVELS  # noqa: E402

logging.disable(logging.CRITICAL)


def main() -> None:
    p = argparse.ArgumentParser(description="策略一 = 因子1+因子2（权益补仓）")
    p.add_argument("--start", default=None, help="起始日 YYYYMMDD")
    p.add_argument("--end", default=None, help="结束日 YYYYMMDD")
    p.add_argument("--rules", action="store_true", help="打印策略一完整规则")
    p.add_argument(
        "--add-pct",
        type=float,
        default=None,
        help=f"因子2每档追加比例，默认 {DEFAULT_ADD_PCT}",
    )
    p.add_argument(
        "--no-factor2",
        action="store_true",
        help="仅因子1",
    )
    args = p.parse_args()

    if args.rules:
        print(get_strategy("strategy1").print_rules())
        return

    cfg = KAICHENG
    kw = {}
    if args.start:
        kw["start_date"] = args.start
    if args.end:
        kw["end_date"] = args.end
    if args.add_pct is not None:
        kw["factor2_add_pct"] = args.add_pct
    if kw:
        cfg = replace(cfg, **kw)

    print(cfg.report_title_suffix())
    print(
        f"因子2默认档位 {[f'{x*100:.0f}%' for x in DEFAULT_LEVELS]}  "
        f"每档+{(args.add_pct if args.add_pct is not None else DEFAULT_ADD_PCT)*100:.0f}%"
    )
    result, _ = run_strategy1(
        cfg,
        show_report=False,
        verbose=True,
        apply_factor2_overlay=not args.no_factor2,
    )
    ov = getattr(result, "factor2_overlay", None)
    if ov is None and not args.no_factor2:
        print("(未生成 factor2_overlay)")


if __name__ == "__main__":
    main()
