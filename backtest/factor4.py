"""策略五 · 动量因子组合回测（中证500+1000主板，2020→今）· 因子3。

默认读取 strategy5.PORTFOLIO_DEFAULTS（挖参后多为短期反转）。

用法:
  python factor3.py --no-open
  python factor4.py --no-open          # 兼容旧入口，同 factor3
  python factor3.py --no-open --universe zz1000_mainboard
  python factor3.py --no-open --kind rev --n 90 --top-k 3 --hold-days 14
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from backtest import zz1000_momentum_select as zz  # noqa: E402
from strategy.backtest import _metric  # noqa: E402
from strategy.dd_alert import yearly_max_drawdowns  # noqa: E402
from strategy.strategies.strategy5.portfolio import (  # noqa: E402
    PORTFOLIO_DEFAULTS,
    apply_best_config,
    run_momentum_portfolio,
)

START = str(PORTFOLIO_DEFAULTS["start"])
WARM = str(PORTFOLIO_DEFAULTS["warm_start"])
OUT_DIR = Path(__file__).resolve().parent / "factor4_out"


def _end_today() -> str:
    return pd.Timestamp.today().strftime("%Y%m%d")


def run_portfolio(
    *,
    kind: str,
    n: int,
    top_k: int,
    hold_days: int,
    min_score: float | None,
    ma_filter: int | None,
    universe: str,
    refresh: bool,
    no_open: bool,
) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result = run_momentum_portfolio(
        kind=kind,
        n=n,
        top_k=top_k,
        hold_days=hold_days,
        min_score=min_score,
        ma_filter=ma_filter,
        universe=universe,
        start=START,
        end=_end_today(),
        warm_start=WARM,
        refresh=refresh,
        verbose=True,
    )
    stats = result.stats
    yearly = result.yearly
    eq = result.equity.set_index("date")["equity"].astype(float).sort_index()
    ydd = yearly_max_drawdowns(eq)
    name_map = result.name_map

    print(f"\n========== 动量因子组合 · {universe} ==========")
    for k in (
        "start",
        "end",
        "n_days",
        "factor",
        "top_k",
        "hold_days",
        "total_return_pct",
        "max_drawdown_pct",
        "sharpe",
        "end_equity",
        "n_trades",
        "n_buys",
    ):
        print(f"{k}: {stats.get(k)}")

    print("\n分年收益 / 年内最大回撤")
    if not yearly.empty:
        print(yearly.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    if ydd is not None and len(ydd):
        print(
            "yearly_max_drawdowns%:",
            {int(k): round(float(v) * 100, 2) for k, v in ydd.items()},
        )

    result.equity.to_csv(OUT_DIR / "zz1000_equity.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(OUT_DIR / "zz1000_yearly.csv", index=False, encoding="utf-8-sig")
    tr_df = result.trades
    if not tr_df.empty:
        tr_df = tr_df.copy()
        tr_df["name"] = tr_df["symbol"].map(name_map)
        tr_df.to_csv(OUT_DIR / "zz1000_trades.csv", index=False, encoding="utf-8-sig")
    pk = result.picks
    if isinstance(pk, pd.DataFrame) and not pk.empty:
        pk = pk.copy()
        pk["pick_names"] = pk["picks"].map(
            lambda s: ",".join(name_map.get(x, x) for x in str(s).split(","))
        )
        pk.to_csv(OUT_DIR / "zz1000_picks.csv", index=False, encoding="utf-8-sig")
        print("\n最近10日选股:")
        print(pk.tail(10).to_string(index=False))

    (OUT_DIR / "zz1000_summary.txt").write_text(
        "\n".join(f"{k}: {stats.get(k)}" for k in stats if k != "picks")
        + "\n\n"
        + yearly.to_string(index=False)
        + "\n",
        encoding="utf-8",
    )

    html = zz._write_html_report(
        eq_df=result.equity,
        tr_df=tr_df if not tr_df.empty else pd.DataFrame(),
        pk_df=pk if isinstance(pk, pd.DataFrame) else pd.DataFrame(),
        stats=stats,
        name_map=name_map,
        initial_cash=zz.INITIAL_CASH,
        note=(
            f"动量因子组合 pool={universe} {kind}(n={n}) Top{top_k}/持有{hold_days}日；"
            f"ma={ma_filter}；回测自{START}。"
        ),
    )
    dest = OUT_DIR / "zz1000_factor4_report.html"
    dest.write_text(html.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"\n产物: {OUT_DIR}")
    print(f"HTML: {dest}")
    if not no_open:
        import os
        import subprocess

        if sys.platform.startswith("win"):
            os.startfile(str(dest))  # type: ignore[attr-defined]
        else:
            subprocess.run(["open", str(dest)], check=False)


def run_kaicheng_akquant(*, force_refresh: bool, no_open: bool) -> None:
    """对照：凯盛单票时序动量（原 dist_hl，非截面组合）。"""
    from strategy.config import KAICHENG
    from strategy.runner import run_momentum
    from dataclasses import replace

    cfg = replace(
        KAICHENG,
        start_date=START,
        end_date=_end_today(),
        initial_cash=100_000.0,
    )
    print(f"[单票对照] 凯盛 dist_hl  {cfg.start_date}→{cfg.end_date}")
    result, _daily = run_momentum(
        cfg,
        show_report=not no_open,
        force_daily_refresh=force_refresh,
    )
    m = result.metrics_df if hasattr(result, "metrics_df") else getattr(result, "metrics", {})
    print(
        f"[单票摘要] 累计收益%={_metric(m, 'total_return_pct'):.2f}  "
        f"最大回撤%={_metric(m, 'max_drawdown_pct'):.2f}  "
        f"夏普={_metric(m, 'sharpe_ratio'):.3f}"
    )


def main(argv: list[str] | None = None) -> None:
    d = PORTFOLIO_DEFAULTS
    p = argparse.ArgumentParser(description="动量因子组合 · 中证500+1000截面回测")
    p.add_argument("--kind", default=str(d["kind"]))
    p.add_argument("--n", type=int, default=int(d["n"]))
    p.add_argument("--top-k", type=int, default=int(d["top_k"]))
    p.add_argument("--hold-days", type=int, default=int(d["hold_days"]))
    p.add_argument("--ma-filter", type=int, default=None)
    p.add_argument("--min-score", type=float, default=None)
    p.add_argument(
        "--universe",
        default=str(d.get("universe") or "zz500_1000_mainboard"),
        help="zz500_1000_mainboard | zz1000_mainboard | zz500_mainboard",
    )
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--no-open", action="store_true")
    p.add_argument("--optimize", action="store_true", help="先挖参再回测")
    p.add_argument("--symbol-only", action="store_true", help="只跑凯盛单票对照")
    p.add_argument("--with-symbol", action="store_true", help="额外跑凯盛单票对照")
    p.add_argument("--force-refresh", action="store_true", help="单票日线强制刷新")
    args = p.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.symbol_only:
        run_kaicheng_akquant(force_refresh=args.force_refresh, no_open=args.no_open)
        return

    kind, n, top_k, hold_days = args.kind, args.n, args.top_k, args.hold_days
    ma_filter = args.ma_filter if args.ma_filter is not None else d.get("ma_filter")
    min_score = args.min_score if args.min_score is not None else d.get("min_score")
    universe = args.universe

    if args.optimize:
        from backtest.optimize_strategy5_portfolio import main as mine_main

        mine_main()
        import json

        best = json.loads((OUT_DIR / "strategy5_best.json").read_text(encoding="utf-8"))
        apply_best_config(best)
        kind = str(best["kind"])
        n = int(best["n"])
        top_k = int(best["top_k"])
        hold_days = int(best["hold_days"])
        ma_filter = best.get("ma_filter")
        min_score = best.get("min_score")
        print(f"采用挖参最优: {best}")

    run_portfolio(
        kind=kind,
        n=n,
        top_k=top_k,
        hold_days=hold_days,
        min_score=min_score,
        ma_filter=ma_filter,
        universe=universe,
        refresh=bool(args.refresh),
        no_open=bool(args.no_open),
    )
    if args.with_symbol:
        run_kaicheng_akquant(force_refresh=args.force_refresh, no_open=True)


if __name__ == "__main__":
    main()
