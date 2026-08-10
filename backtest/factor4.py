"""中证1000 主板截面选股回测（2020→今）。

说明：
  · 单票策略五/因子4（dist_hl）不适合直接做截面 TopK（无超额 + 换手成本过大）。
  · 截面默认改用 dig 最优：短期反转 rev(n=60) + Top2 + 持有6日袖套轮动。
  · 股票池：中证1000 主板（剔科创/创业/北交）
  · 每天收盘按因子截面选 TopK → 次日开盘买 → 持有 hold_days 日开盘卖

用法:
  python factor4.py --no-open
  python factor4.py --no-open --kind rev --n 60 --top-k 2 --hold-days 6
  python factor4.py --no-open --legacy-dist-hl   # 旧口径对照（不推荐）
  python factor4.py --symbol-only                # 凯盛单票·策略五 dist_hl
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
from strategy.dd_alert import max_drawdown_pct, yearly_max_drawdowns  # noqa: E402
from strategy.momentum import DEFAULT_KIND, DEFAULT_PARAMS  # noqa: E402

START = "20200101"
WARM = "20180101"
INITIAL = zz.INITIAL_CASH
OUT_DIR = Path(__file__).resolve().parent / "factor4_out"

# 截面 dig 默认（见 zz1000_momentum_select/best_config.json）
CS_KIND = "rev"
CS_N = 60
CS_TOP_K = 2
CS_HOLD_DAYS = 6


def _end_today() -> str:
    return pd.Timestamp.today().strftime("%Y%m%d")


def _yearly_table(eq: pd.Series, *, initial_cash: float) -> pd.DataFrame:
    eq = eq.dropna().sort_index()
    if eq.empty:
        return pd.DataFrame()
    if getattr(eq.index, "tz", None) is not None:
        years = eq.index.tz_convert("Asia/Shanghai").year
    else:
        years = eq.index.year
    rows: list[dict] = []
    for y, g in eq.groupby(years):
        prev = eq[eq.index < g.index[0]]
        base = float(prev.iloc[-1]) if len(prev) else float(initial_cash)
        ret = float(g.iloc[-1] / base - 1.0) * 100
        dd = max_drawdown_pct(g) * 100 if len(g) > 1 else 0.0
        rows.append({"year": int(y), "return_pct": ret, "max_dd_pct": dd})
    return pd.DataFrame(rows)


def run_zz1000_cross_section(
    *,
    kind: str,
    n: int,
    top_k: int,
    hold_days: int,
    refresh: bool,
    no_open: bool,
) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    end = _end_today()
    print(
        f"[中证1000截面] pool=主板  kind={kind} n={n} "
        f"top_k={top_k} hold_days={hold_days}  {START}→{end}"
    )

    univ = zz.load_zz1000_mainboard()
    name_map = dict(zip(univ["symbol"], univ["name"]))
    opens, highs, lows, closes = zz.load_panel_matrices(
        univ["symbol"].tolist(),
        warm_start=WARM,
        end=end,
        refresh=refresh,
    )
    print(f"面板 close={closes.shape}")

    factor = zz.compute_factor(
        opens,
        highs,
        lows,
        closes,
        kind=kind,
        n=n,
        min_score=None,
        ma_filter=None,
    )
    label = f"{kind}{{n={n}, hold={hold_days}}}"
    print(f"计算因子 {label} → {factor.shape}")

    picks = zz.daily_topk(factor, top_k)
    bt_start = pd.Timestamp(START)
    idx_tz = getattr(factor.index, "tz", None)
    if idx_tz is not None:
        bt_start = bt_start.tz_localize(idx_tz)

    eq_df, tr_df, stats = zz.simulate(
        factor=factor,
        opens=opens,
        closes=closes,
        picks=picks,
        bt_start=bt_start,
        hold_days=hold_days,
        top_k=top_k,
        initial_cash=INITIAL,
        factor_label=label,
    )
    if eq_df is None or eq_df.empty:
        print("无权益曲线，退出")
        return

    eq = eq_df.set_index("date")["equity"].astype(float).sort_index()
    yearly = _yearly_table(eq, initial_cash=INITIAL)
    ydd = yearly_max_drawdowns(eq)

    print("\n========== 中证1000 · 截面 TopK ==========")
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

    eq_df.to_csv(OUT_DIR / "zz1000_equity.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(OUT_DIR / "zz1000_yearly.csv", index=False, encoding="utf-8-sig")
    if not tr_df.empty:
        tr_df = tr_df.copy()
        tr_df["name"] = tr_df["symbol"].map(name_map)
        tr_df.to_csv(OUT_DIR / "zz1000_trades.csv", index=False, encoding="utf-8-sig")
    pk = stats.get("picks")
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
        eq_df=eq_df,
        tr_df=tr_df if not tr_df.empty else pd.DataFrame(),
        pk_df=pk if isinstance(pk, pd.DataFrame) else pd.DataFrame(),
        stats=stats,
        name_map=name_map,
        initial_cash=INITIAL,
        note=(
            f"截面修复口径：{kind}(n={n}) Top{top_k} 持有{hold_days}日；"
            f"不再把单票 dist_hl 直接当截面动量。回测自{START}。"
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
    """可选对照：凯盛单票 · 策略 factor4 / strategy5（时序 dist_hl）。"""
    from strategy import get_strategy

    cfg_base = get_strategy("factor4").default_config()
    cfg = replace_cfg(
        cfg_base,
        start=START,
        end=_end_today(),
        warm_start=WARM,
        initial_cash=100_000.0,
    )
    print(f"[单票对照] 凯盛 factor4/dist_hl  {cfg.start}→{cfg.end}")
    result, daily = get_strategy("factor4").run(
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


def replace_cfg(cfg, **kwargs):
    from dataclasses import replace

    return replace(cfg, **kwargs)


def main(argv: list[str] | None = None) -> None:
    best = zz.load_best_config()
    p = argparse.ArgumentParser(description="中证1000截面选股回测（修复口径）")
    p.add_argument("--kind", default=str(best.get("kind", CS_KIND)))
    p.add_argument("--n", type=int, default=int(best.get("n", CS_N)))
    p.add_argument("--top-k", type=int, default=int(best.get("top_k", CS_TOP_K)))
    p.add_argument(
        "--hold-days", type=int, default=int(best.get("hold_days", CS_HOLD_DAYS))
    )
    p.add_argument(
        "--legacy-dist-hl",
        action="store_true",
        help="旧口径：dist_hl Top5/持有5（仅对照，已知截面失效）",
    )
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--no-open", action="store_true")
    p.add_argument("--symbol-only", action="store_true", help="只跑凯盛单票对照")
    p.add_argument("--with-symbol", action="store_true", help="额外跑凯盛单票对照")
    p.add_argument("--force-refresh", action="store_true", help="单票日线强制刷新")
    args = p.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.symbol_only:
        run_kaicheng_akquant(force_refresh=args.force_refresh, no_open=args.no_open)
        return

    kind, n, top_k, hold_days = args.kind, args.n, args.top_k, args.hold_days
    if args.legacy_dist_hl:
        kind = DEFAULT_KIND
        n = int(DEFAULT_PARAMS["n"])
        top_k = 5
        hold_days = 5

    run_zz1000_cross_section(
        kind=kind,
        n=n,
        top_k=top_k,
        hold_days=hold_days,
        refresh=bool(args.refresh),
        no_open=bool(args.no_open),
    )
    if args.with_symbol:
        run_kaicheng_akquant(force_refresh=args.force_refresh, no_open=True)


if __name__ == "__main__":
    main()
