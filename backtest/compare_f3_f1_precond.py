"""对照：因子3选股 ± 因子1前置/突破买卖。

用法：
  cd backtest
  python compare_f3_f1_precond.py
  python compare_f3_f1_precond.py --start 20200101 --top-k 3 --hold-days 20
  python compare_f3_f1_precond.py --rules
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from strategy.f3_f1_combo import (  # noqa: E402
    COMBO_DEFAULTS,
    combo_rules_text,
    run_f3_f1_combo,
)
from strategy.open_break import DEFAULT_PCT  # noqa: E402
from strategy.strategies._unreg_s6.portfolio import (  # noqa: E402
    run_f3_select_f1_stop_portfolio,
)


def _fmt(v: object, nd: int = 2) -> str:
    try:
        x = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "-"
    if x != x:
        return "-"
    return f"{x:,.{nd}f}"


def main() -> None:
    p = argparse.ArgumentParser(description="因子3 × 因子1前置/买卖对照")
    p.add_argument("--rules", action="store_true", help="打印组合规则后退出")
    p.add_argument("--entry", type=float, default=DEFAULT_PCT)
    p.add_argument("--stop", type=float, default=DEFAULT_PCT)
    p.add_argument("--hold-days", type=int, default=None, help="可选到期日；默认只止损")
    p.add_argument("--top-k", type=int, default=None)
    p.add_argument("--n", type=int, default=None)
    p.add_argument("--start", type=str, default=None)
    p.add_argument("--end", type=str, default=None)
    p.add_argument("--refresh", action="store_true")
    p.add_argument(
        "--skip-old",
        action="store_true",
        help="只跑新组合（带前置+突破买），跳过旧开盘买对照",
    )
    args = p.parse_args()

    if args.rules:
        print(
            combo_rules_text(
                entry_pct=float(args.entry),
                stop_pct=float(args.stop),
                top_k=int(args.top_k or COMBO_DEFAULTS["top_k"]),
                hold_days=args.hold_days,
            )
        )
        return

    common = {
        "kind": COMBO_DEFAULTS["kind"],
        "n": args.n or COMBO_DEFAULTS["n"],
        "top_k": args.top_k or COMBO_DEFAULTS["top_k"],
        "start": args.start or COMBO_DEFAULTS["start"],
        "end": args.end,
        "refresh": args.refresh,
        "verbose": True,
    }
    hold = args.hold_days

    rows: list[tuple[str, dict]] = []

    if not args.skip_old:
        print("===== A 旧对照：因子3选股 + 开盘买 + 因子1止损/到期 =====")
        old_hold = int(hold if hold is not None else 20)
        a = run_f3_select_f1_stop_portfolio(
            **common, hold_days=old_hold, stop_pct=float(args.stop)
        )
        rows.append(("A旧开盘买", a.stats))

    print("===== B 新组合：因子1前置 + 因子3选股 + 因子1突破买/止损 =====")
    b = run_f3_f1_combo(
        **common,
        hold_days=hold,
        entry_pct=float(args.entry),
        stop_pct=float(args.stop),
        require_f1_precond=True,
    )
    rows.append(("B前置+突破", b.stats))

    print("===== C 消融：无前置，仍用因子1突破买/止损 =====")
    c = run_f3_f1_combo(
        **common,
        hold_days=hold,
        entry_pct=float(args.entry),
        stop_pct=float(args.stop),
        require_f1_precond=False,
    )
    rows.append(("C无前置突破", c.stats))

    print("\n========== 对照摘要 ==========")
    headers = ["指标"] + [name for name, _ in rows]
    print(" | ".join(f"{h:>14}" for h in headers))
    metrics = [
        ("累计收益%", "total_return_pct"),
        ("最大回撤%", "max_drawdown_pct"),
        ("夏普", "sharpe"),
        ("买入笔数", "n_buys"),
        ("止损卖出", "n_stop_exits"),
        ("到期卖出", "n_time_exits"),
        ("未触发突破", "n_breakout_miss"),
        ("期末权益", "end_equity"),
    ]
    for label, key in metrics:
        vals = [_fmt(st.get(key)) for _, st in rows]
        print(f"{label:>14} | " + " | ".join(f"{v:>14}" for v in vals))

    if not b.yearly.empty:
        print("\nB 分年收益%")
        print(b.yearly.to_string(index=False))


if __name__ == "__main__":
    main()
