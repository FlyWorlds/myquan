"""凯盛科技 因子1 T+1：优化前(945/阴线全清) vs 软减半(945/阴线减半·止损全清)。"""

from __future__ import annotations

import logging
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.disable(logging.CRITICAL)

from strategy.backtest import metric
from strategy.config import KAICHENG
from strategy.runner import run_open_break

ROOT = Path(__file__).resolve().parent


def main() -> None:
    base = replace(
        KAICHENG,
        start_date="20200101",
        t0=False,
        enable_dd_sizing=False,
        report_path=None,
    )

    schemes: list[tuple[str, bool]] = [
        ("优化前_全清", False),
        ("优化后_软减半", True),
    ]

    rows: list[dict] = []
    for name, soft in schemes:
        cfg = replace(
            base,
            enable_soft_half_exit=soft,
            report_path=ROOT
            / f"{KAICHENG.symbol_name}_因子1_T1_{name}_report.html",
        )
        print(f"######## {name} ########", flush=True)
        result, daily = run_open_break(cfg, show_report=False, verbose=True)
        m = result.metrics_df
        c0 = float(daily["close"].iloc[0])
        c1 = float(daily["close"].iloc[-1])
        rows.append(
            {
                "方案": name,
                "累计收益%": metric(m, "total_return_pct"),
                "最大回撤%": metric(m, "max_drawdown_pct"),
                "夏普": metric(m, "sharpe_ratio"),
                "卡玛": metric(m, "calmar_ratio"),
                "胜率%": metric(m, "win_rate"),
                "闭环": metric(m, "closed_trade_count"),
                "期末市值": metric(m, "end_market_value"),
                "成交笔数": len(result.executions_df),
                "价格涨幅%": (c1 / c0 - 1.0) * 100.0,
            }
        )
        if cfg.report_path is not None:
            result.viz.report(
                title=f"{cfg.symbol_name} {cfg.report_title_suffix()}",
                filename=str(cfg.report_path),
                show=False,
                market_data=daily,
                plot_symbol=cfg.symbol,
                curve_freq="D",
            )
            print(f"报告: {cfg.report_path}", flush=True)

    print("\n========== 凯盛科技 因子1 软减半对比 ==========")
    df = pd.DataFrame(rows)
    show = [c for c in df.columns if c != "价格涨幅%"]
    print(df[show].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"\n买入持有(首收→末收): {rows[0]['价格涨幅%']:.2f}%")
    a, b = rows[0], rows[1]
    print("\n差异 (优化后 - 优化前):")
    for k in ("累计收益%", "最大回撤%", "夏普", "卡玛", "胜率%", "闭环", "期末市值", "成交笔数"):
        print(f"  {k}: {b[k] - a[k]:+.4f}")


if __name__ == "__main__":
    main()
