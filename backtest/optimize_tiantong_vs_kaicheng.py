"""天通/凯盛：因子1变体 + 因子3动量 对照实验（相对现行仅止损）。

用法：
  python optimize_tiantong_vs_kaicheng.py
  python optimize_tiantong_vs_kaicheng.py --symbol tiantong
"""

from __future__ import annotations

import argparse
import sys
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

from strategy import KAICHENG, run_open_break  # noqa: E402
from strategy.backtest import OpenBreak3Strategy, metric  # noqa: E402
from strategy.base import run_backtest_pipeline  # noqa: E402
from strategy.config import _DAILY_CACHE_DIR  # noqa: E402
from strategy.runner import apply_strategy_config, run_momentum  # noqa: E402

OUT = Path(__file__).resolve().parent / "optimize_tiantong_vs_kaicheng.csv"

TIANTONG = replace(
    KAICHENG,
    symbol="sh600330",
    symbol_name="天通股份",
    em_symbol="600330",
    daily_cache=_DAILY_CACHE_DIR / "sh600330_daily_qfq.parquet",
)


def _stats(result: Any, label: str, symbol: str) -> dict[str, Any]:
    m = result.metrics_df
    td = result.trades_df
    out: dict[str, Any] = {
        "标的": symbol,
        "方案": label,
        "累计%": round(float(metric(m, "total_return_pct")), 2),
        "回撤%": round(float(metric(m, "max_drawdown_pct")), 2),
        "夏普": round(float(metric(m, "sharpe_ratio")), 3),
        "胜率%": round(float(metric(m, "win_rate")), 2),
        "闭环": int(metric(m, "closed_trade_count")),
        "利润因子": round(float(metric(m, "profit_factor")), 3),
        "均盈%": None,
        "均亏%": None,
        "盈亏比": None,
        "相对基线累计差": None,
    }
    if td is not None and not td.empty and "return_pct" in td.columns:
        w = td.loc[td["pnl"] > 0, "return_pct"]
        l = td.loc[td["pnl"] <= 0, "return_pct"]
        aw = float(w.mean()) if len(w) else float("nan")
        al = float(l.mean()) if len(l) else float("nan")
        out["均盈%"] = round(aw, 2) if aw == aw else None
        out["均亏%"] = round(al, 2) if al == al else None
        if al == al and al != 0:
            out["盈亏比"] = round(abs(aw / al), 2)
    return out


def _run_f1(cfg: Any, label: str, symbol: str) -> dict[str, Any]:
    r, _ = run_open_break(cfg, show_report=False, verbose=False)
    return _stats(r, label, symbol)


def _run_f1_asym(
    cfg: Any,
    *,
    entry: float,
    stop: float,
    label: str,
    symbol: str,
) -> dict[str, Any]:
    c = replace(cfg, threshold_pct=entry)

    def configure(strategy: OpenBreak3Strategy, params: Any) -> None:
        apply_strategy_config(strategy, params)
        strategy.entry_pct = entry
        strategy.stop_pct = stop
        strategy.prev_small_yang_pct = entry

    r, _ = run_backtest_pipeline(
        params=c,
        strategy_cls=OpenBreak3Strategy,
        configure=configure,
        print_summary_fn=None,
        show_report=False,
        verbose=False,
    )
    return _stats(r, label, symbol)


def _run_mom(cfg: Any, kind: str, params: dict, label: str, symbol: str) -> dict[str, Any]:
    c = replace(cfg, mom_kind=kind, mom_params=params)
    r, _ = run_momentum(c, show_report=False, verbose=False)
    return _stats(r, label, symbol)


def variants_for(base: Any) -> list[tuple[str, Callable[[], dict[str, Any]]]]:
    name = base.symbol_name
    jobs: list[tuple[str, Callable[[], dict[str, Any]]]] = []

    jobs.append(
        (
            "F1基线±2.5%仅止损",
            lambda: _run_f1(base, "F1基线±2.5%仅止损", name),
        )
    )
    jobs.append(
        (
            "F1±2.0%",
            lambda: _run_f1(replace(base, threshold_pct=0.02), "F1±2.0%", name),
        )
    )
    jobs.append(
        (
            "F1±3.0%",
            lambda: _run_f1(replace(base, threshold_pct=0.03), "F1±3.0%", name),
        )
    )
    jobs.append(
        (
            "F1仅阴±2.5%",
            lambda: _run_f1(
                replace(base, prev_entry_mode="yin_only"),
                "F1仅阴±2.5%",
                name,
            ),
        )
    )
    jobs.append(
        (
            "F1仅阴±3%(策略二)",
            lambda: _run_f1(
                replace(base, threshold_pct=0.03, prev_entry_mode="yin_only"),
                "F1仅阴±3%(策略二)",
                name,
            ),
        )
    )
    jobs.append(
        (
            "F1隔日止损跳买",
            lambda: _run_f1(
                replace(base, skip_buy_after_overnight_stop=True),
                "F1隔日止损跳买",
                name,
            ),
        )
    )
    jobs.append(
        (
            "F1连亏2次跳买",
            lambda: _run_f1(
                replace(base, skip_buy_after_consec_stops=2),
                "F1连亏2次跳买",
                name,
            ),
        )
    )
    jobs.append(
        (
            "F1买2.5/止3.5",
            lambda: _run_f1_asym(
                base, entry=0.025, stop=0.035, label="F1买2.5/止3.5", symbol=name
            ),
        )
    )
    jobs.append(
        (
            "F1买2.5/止4.0",
            lambda: _run_f1_asym(
                base, entry=0.025, stop=0.040, label="F1买2.5/止4.0", symbol=name
            ),
        )
    )
    jobs.append(
        (
            "F1买3/止2.5宽买窄止",
            lambda: _run_f1_asym(
                base, entry=0.03, stop=0.025, label="F1买3/止2.5宽买窄止", symbol=name
            ),
        )
    )
    # 因子4：凯盛默认 dist_hl；再试几组常见动量
    mom_grid = [
        ("dist_hl", {"n": 120, "enter": 1.0, "exit": 0.0}, "F4 dist_hl n120"),
        ("dist_hl", {"n": 60, "enter": 1.0, "exit": 0.0}, "F4 dist_hl n60"),
        ("roc", {"n": 20}, "F4 roc20"),
        ("roc", {"n": 60}, "F4 roc60"),
        ("breakout", {"n": 20}, "F4 breakout20"),
        ("dual_ma", {"fast": 10, "slow": 30}, "F4 dual_ma10/30"),
        ("ma", {"n": 60}, "F4 ma60"),
    ]
    for kind, params, label in mom_grid:
        jobs.append(
            (
                label,
                lambda k=kind, p=params, lb=label: _run_mom(base, k, p, lb, name),
            )
        )
    return jobs


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--symbol",
        choices=("both", "tiantong", "kaicheng"),
        default="both",
    )
    args = p.parse_args()

    bases: list[Any] = []
    if args.symbol in ("both", "kaicheng"):
        bases.append(KAICHENG)
    if args.symbol in ("both", "tiantong"):
        bases.append(TIANTONG)

    rows: list[dict[str, Any]] = []
    for base in bases:
        print(f"\n===== {base.symbol_name} =====")
        jobs = variants_for(base)
        baseline_ret: float | None = None
        for i, (label, fn) in enumerate(jobs, 1):
            print(f"  [{i}/{len(jobs)}] {label} ...", flush=True)
            try:
                row = fn()
            except Exception as e:  # noqa: BLE001
                print(f"    FAIL: {e}")
                continue
            if baseline_ret is None and label.startswith("F1基线"):
                baseline_ret = float(row["累计%"])
            if baseline_ret is not None:
                row["相对基线累计差"] = round(float(row["累计%"]) - baseline_ret, 2)
            rows.append(row)
            print(
                f"    累计{row['累计%']}% 回撤{row['回撤%']}% "
                f"夏普{row['夏普']} 胜率{row['胜率%']}% "
                f"差{row['相对基线累计差']}"
            )

    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"\n已写入 {OUT}")

    print("\n===== 各标的相对基线 Top5 =====")
    for sym, g in df.groupby("标的"):
        g2 = g.sort_values("相对基线累计差", ascending=False).head(5)
        print(f"\n[{sym}]")
        print(
            g2[
                ["方案", "累计%", "回撤%", "夏普", "胜率%", "盈亏比", "相对基线累计差"]
            ].to_string(index=False)
        )


if __name__ == "__main__":
    main()
