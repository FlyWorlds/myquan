"""凯盛科技 因子1 T+1 仓位管理对比：无 / 默认20·15 / 优化22·5。"""

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

# 网格搜索最优（夏普=卡玛）：半仓 22%、回撤 <5% 恢复全仓
BEST_HALF = 0.22
BEST_FULL = 0.05


def main() -> None:
    base = replace(
        KAICHENG,
        start_date="20200101",
        t0=False,
        report_path=None,
    )

    schemes: list[tuple[str, bool, float, float]] = [
        ("无回撤仓位", False, 0.20, 0.15),
        ("默认20/15", True, 0.20, 0.15),
        ("最优22/5", True, BEST_HALF, BEST_FULL),
    ]

    rows: list[dict] = []
    for name, dd_on, half, full in schemes:
        tag = name.replace("/", "-")
        cfg = replace(
            base,
            enable_dd_sizing=dd_on,
            dd_half_pct=half,
            dd_full_pct=full,
            report_path=ROOT / f"{KAICHENG.symbol_name}_因子1_T1_{tag}_report.html",
        )
        print(f"######## {name} ########", flush=True)
        result, daily = run_open_break(cfg, show_report=False, verbose=True)
        m = result.metrics_df
        c0 = float(daily["close"].iloc[0])
        c1 = float(daily["close"].iloc[-1])
        rows.append(
            {
                "方案": name,
                "半仓%": half * 100 if dd_on else None,
                "恢复%": full * 100 if dd_on else None,
                "累计收益%": metric(m, "total_return_pct"),
                "最大回撤%": metric(m, "max_drawdown_pct"),
                "夏普": metric(m, "sharpe_ratio"),
                "卡玛": metric(m, "calmar_ratio"),
                "胜率%": metric(m, "win_rate"),
                "闭环": metric(m, "closed_trade_count"),
                "期末市值": metric(m, "end_market_value"),
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

    print("\n========== 凯盛科技 因子1 T+1 仓位管理对比 ==========")
    df = pd.DataFrame(rows)
    show = [c for c in df.columns if c != "价格涨幅%"]
    print(df[show].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"\n买入持有(首收→末收): {rows[0]['价格涨幅%']:.2f}%")

    base_row = rows[0]
    for r in rows[1:]:
        print(f"\n差异 ({r['方案']} - 无回撤仓位):")
        for k in ("累计收益%", "最大回撤%", "夏普", "卡玛", "期末市值"):
            print(f"  {k}: {r[k] - base_row[k]:+.4f}")


if __name__ == "__main__":
    main()
