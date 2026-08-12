"""对照：策略五纯袖套 vs 策略六（因子3选股 + 因子1止损）。

用法：
  cd backtest
  python compare_f3_select_f1_stop.py
  python compare_f3_select_f1_stop.py --stop 0.03 --hold-days 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from strategy.open_break import DEFAULT_PCT  # noqa: E402
from strategy.strategies.strategy5.portfolio import (  # noqa: E402
    PORTFOLIO_DEFAULTS,
    run_momentum_portfolio,
)
from strategy.strategies.strategy6.portfolio import (  # noqa: E402
    run_f3_select_f1_stop_portfolio,
)


def _fmt(v: float, nd: int = 2) -> str:
    if v != v:  # NaN
        return "-"
    return f"{v:,.{nd}f}"


def main() -> None:
    p = argparse.ArgumentParser(description="因子3选股 ± 因子1止损对照")
    p.add_argument("--stop", type=float, default=DEFAULT_PCT, help="因子1止损pct")
    p.add_argument("--hold-days", type=int, default=None)
    p.add_argument("--top-k", type=int, default=None)
    p.add_argument("--n", type=int, default=None)
    p.add_argument("--start", type=str, default=None)
    p.add_argument("--end", type=str, default=None)
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()

    common = {
        "kind": PORTFOLIO_DEFAULTS["kind"],
        "n": args.n or PORTFOLIO_DEFAULTS["n"],
        "top_k": args.top_k or PORTFOLIO_DEFAULTS["top_k"],
        "hold_days": args.hold_days or PORTFOLIO_DEFAULTS["hold_days"],
        "start": args.start or PORTFOLIO_DEFAULTS["start"],
        "end": args.end,
        "refresh": args.refresh,
        "verbose": True,
    }

    print("===== A 策略五：因子3选股 + 袖套到期卖（无止损）=====")
    a = run_momentum_portfolio(**common)
    print("===== B 策略六：因子3选股 + 因子1止损（未触则到期卖）=====")
    b = run_f3_select_f1_stop_portfolio(**common, stop_pct=float(args.stop))

    sa, sb = a.stats, b.stats
    print("\n========== 对照摘要 ==========")
    print(
        f"参数: kind={common['kind']} n={common['n']} top_k={common['top_k']} "
        f"hold={common['hold_days']} stop_B={float(args.stop)*100:.1f}% "
        f"{common['start']}→{sa.get('end')}"
    )
    rows = [
        ("累计收益%", sa.get("total_return_pct"), sb.get("total_return_pct")),
        ("最大回撤%", sa.get("max_drawdown_pct"), sb.get("max_drawdown_pct")),
        ("夏普", sa.get("sharpe"), sb.get("sharpe")),
        ("买入笔数", sa.get("n_buys"), sb.get("n_buys")),
        ("止损卖出", 0, sb.get("n_stop_exits")),
        ("到期卖出", sa.get("n_buys"), sb.get("n_time_exits")),
        ("期末权益", sa.get("end_equity"), sb.get("end_equity")),
    ]
    print(f"{'指标':<12} {'A纯袖套':>16} {'B+因子1止损':>16} {'差值(B-A)':>16}")
    for name, va, vb in rows:
        try:
            da = float(va) if va is not None else float("nan")
            db = float(vb) if vb is not None else float("nan")
            diff = db - da
        except (TypeError, ValueError):
            da = db = diff = float("nan")
        print(f"{name:<12} {_fmt(da):>16} {_fmt(db):>16} {_fmt(diff):>16}")

    if not b.yearly.empty:
        print("\nB 分年收益%")
        print(b.yearly.to_string(index=False))


if __name__ == "__main__":
    main()
