"""HK1888 因子1 T+1：无回撤仓位 vs 回撤20%半仓/15%恢复全仓。"""

from __future__ import annotations

import logging
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.disable(logging.CRITICAL)

from strategy.backtest import metric
from strategy.config import HK1888
from strategy.runner import run_open_break

ROOT = Path(__file__).resolve().parent


def main() -> None:
    base = replace(
        HK1888,
        start_date="20200101",
        end_date="20260804",
        t0=False,
        report_path=None,
    )

    rows: list[dict] = []
    for name, dd_on in (
        ("无回撤仓位", False),
        ("回撤20/15仓位", True),
    ):
        cfg = replace(
            base,
            enable_dd_sizing=dd_on,
            report_path=ROOT
            / (
                f"{HK1888.symbol_name}_因子1_T1_"
                f"{'回撤仓位' if dd_on else '无回撤仓位'}_report.html"
            ),
        )
        print(f"######## {name} ########", flush=True)
        result, daily = run_open_break(cfg, show_report=False, verbose=True)
        m = result.metrics_df
        rows.append(
            {
                "方案": name,
                "累计收益%": metric(m, "total_return_pct"),
                "最大回撤%": metric(m, "max_drawdown_pct"),
                "夏普": metric(m, "sharpe_ratio"),
                "胜率%": metric(m, "win_rate"),
                "闭环": metric(m, "closed_trade_count"),
                "期末市值": metric(m, "end_market_value"),
                "成交笔数": len(result.executions_df),
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

    print("\n========== HK1888 因子1 T+1 仓位管理对比 ==========")
    df = pd.DataFrame(rows)
    print(df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    a, b = rows[0], rows[1]
    print("\n差异 (回撤仓位 - 无):")
    for k in ("累计收益%", "最大回撤%", "夏普", "胜率%", "闭环", "期末市值", "成交笔数"):
        print(f"  {k}: {b[k] - a[k]:+.4f}")


if __name__ == "__main__":
    main()
