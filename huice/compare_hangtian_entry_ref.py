"""航天电子：现策略 vs 前日小阳开盘算买点 全量回测对比。"""

from __future__ import annotations

import logging
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy import HANGTIANDIANZI, run_open_break

logging.disable(logging.CRITICAL)

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / f"{HANGTIANDIANZI.symbol}_1m_qfq.parquet"


def _metrics(result) -> dict[str, float]:
    m = result.metrics_df
    out: dict[str, float] = {}
    for k in (
        "total_return",
        "max_drawdown",
        "sharpe_ratio",
        "win_rate",
        "total_trades",
        "profit_factor",
        "calmar_ratio",
    ):
        if k in m.index:
            out[k] = float(m.loc[k].iloc[0])
    eq = result.equity_curve
    if eq is not None and len(eq) > 0:
        if hasattr(eq, "columns"):
            col = "equity" if "equity" in eq.columns else eq.columns[0]
            out["期末权益"] = float(eq[col].iloc[-1])
        else:
            out["期末权益"] = float(eq.iloc[-1])
    return out


def _print_block(title: str, result, daily: pd.DataFrame, cfg) -> dict[str, float]:
    from strategy.backtest import print_summary

    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)
    print_summary(
        result,
        daily,
        symbol_name=cfg.symbol_name,
        symbol=cfg.symbol,
        initial_cash=cfg.initial_cash,
        commission_rate=cfg.commission_rate,
        stamp_tax_rate=cfg.stamp_tax_rate,
        slippage_value=cfg.slippage_value,
        entry_pct=cfg.threshold_pct,
        stop_pct=cfg.threshold_pct,
        prev_small_yang_pct=cfg.threshold_pct,
    )
    return _metrics(result)


def main() -> None:
    base = replace(
        HANGTIANDIANZI,
        min1_cache=CACHE,
        report_path=None,
    )

    cfg_cur = replace(
        base,
        entry_ref="today_open",
        report_path=ROOT / "航天电子_report.html",
    )
    cfg_opt = replace(
        base,
        entry_ref="prev_open_on_small_yang",
        report_path=ROOT / "航天电子_prevOpen买点_report.html",
    )

    print("【A】当前策略：买点 = ceil(今日开盘 × 1.025)")
    r1, d1 = run_open_break(cfg_cur, show_report=False, verbose=False)
    m1 = _print_block("A 当前策略（今日开盘算买点）", r1, d1, cfg_cur)
    cfg_cur.report_path = ROOT / "航天电子_report.html"
    r1.viz.report(
        title=f"{cfg_cur.symbol_name} {cfg_cur.report_title_suffix()}",
        filename=str(cfg_cur.report_path),
        show=False,
        market_data=d1,
        plot_symbol=cfg_cur.symbol,
        curve_freq="D",
    )
    print(f"报告: {cfg_cur.report_path}")

    print("\n【B】优化策略：前日小阳时买点 = ceil(前日开盘 × 1.025)；阴线日仍用今日开盘")
    r2, d2 = run_open_break(cfg_opt, show_report=False, verbose=False)
    m2 = _print_block("B 优化策略（前日小阳开盘算买点）", r2, d2, cfg_opt)
    r2.viz.report(
        title=f"{cfg_opt.symbol_name} {cfg_opt.report_title_suffix()}",
        filename=str(cfg_opt.report_path),
        show=False,
        market_data=d2,
        plot_symbol=cfg_opt.symbol,
        curve_freq="D",
    )
    print(f"报告: {cfg_opt.report_path}")

    print("\n" + "=" * 72)
    print("对比汇总（航天电子 2020→今）")
    print("=" * 72)
    rows = [
        ("累计收益%", "total_return", True),
        ("最大回撤%", "max_drawdown", False),  # 回撤越小越好（通常为负或正百分比）
        ("夏普", "sharpe_ratio", True),
        ("胜率%", "win_rate", True),
        ("闭环交易", "total_trades", None),
        ("盈亏比", "profit_factor", True),
        ("Calmar", "calmar_ratio", True),
        ("期末权益", "期末权益", True),
    ]
    print(f"{'指标':<12}{'A今日开盘':>14}{'B前日小阳开':>14}{'更好':>10}")
    for name, key, higher_better in rows:
        a = m1.get(key)
        b = m2.get(key)
        if a is None or b is None:
            print(f"{name:<12}{str(a):>14}{str(b):>14}{'—':>10}")
            continue
        if higher_better is None:
            winner = "—"
        else:
            # max_drawdown: metrics often store as positive fraction or negative
            aa, bb = float(a), float(b)
            if key == "max_drawdown":
                # 绝对值更小更好
                winner = "A" if abs(aa) < abs(bb) - 1e-12 else ("B" if abs(bb) < abs(aa) - 1e-12 else "平")
            elif higher_better:
                winner = "A" if aa > bb + 1e-12 else ("B" if bb > aa + 1e-12 else "平")
            else:
                winner = "A" if aa < bb - 1e-12 else ("B" if bb < aa - 1e-12 else "平")
        print(f"{name:<12}{float(a):>14.4f}{float(b):>14.4f}{winner:>10}")


if __name__ == "__main__":
    main()
