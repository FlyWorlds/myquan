"""因子1：持股一日、次日开盘清 — 2025 / 2026 胜率与收益。

  python strategy/strategies/strategy1/optimize_tests/run_hold1_next_open.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from dataclasses import replace
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[4]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from strategy.backtest import metric  # noqa: E402
from strategy.config import KAICHENG, TIANTONG  # noqa: E402
from strategy.runner import run_open_break  # noqa: E402

OUT = Path(__file__).resolve().parent / "hold1_next_open"
OUT.mkdir(parents=True, exist_ok=True)

YEARS = ("2025", "2026")


def _trade_stats(result) -> dict:
    trades = getattr(result, "trades_df", None)
    if trades is None or getattr(trades, "empty", True):
        return {
            "n_trades": 0,
            "win_rate": float("nan"),
            "avg_pnl_pct": float("nan"),
            "med_pnl_pct": float("nan"),
            "sum_pnl_pct": float("nan"),
        }
    df = trades.copy()
    if "exit_time" in df.columns:
        df = df[df["exit_time"].notna()]
    if df.empty:
        return {
            "n_trades": 0,
            "win_rate": float("nan"),
            "avg_pnl_pct": float("nan"),
            "med_pnl_pct": float("nan"),
            "sum_pnl_pct": float("nan"),
        }
    # 用成交价差算单笔收益%（与 return_pct 同口径，避免量纲误判）
    if "entry_price" in df.columns and "exit_price" in df.columns:
        rets = (
            pd.to_numeric(df["exit_price"], errors="coerce")
            / pd.to_numeric(df["entry_price"], errors="coerce")
            - 1.0
        ) * 100.0
    elif "return_pct" in df.columns:
        rets = pd.to_numeric(df["return_pct"], errors="coerce")
    else:
        rets = pd.Series(dtype=float)
    rets = rets.dropna()
    n = int(len(rets))
    if n == 0:
        return {
            "n_trades": 0,
            "win_rate": float("nan"),
            "avg_pnl_pct": float("nan"),
            "med_pnl_pct": float("nan"),
            "sum_pnl_pct": float("nan"),
        }
    wins = int((rets > 0).sum())
    return {
        "n_trades": n,
        "win_rate": wins / n * 100.0,
        "avg_pnl_pct": float(rets.mean()),
        "med_pnl_pct": float(rets.median()),
        "sum_pnl_pct": float(rets.sum()),
    }


def run_year(base_cfg, year: str) -> dict:
    start = f"{year}0101"
    end = f"{year}1231"
    cfg = replace(
        base_cfg,
        start_date=start,
        end_date=end,
        exit_next_open=True,
        take_profit_levels=None,
        ma_tp_enabled=False,
        factor4_enabled=False,
    )
    result, daily = run_open_break(cfg, show_report=False, verbose=False)
    m = result.metrics_df
    ts = _trade_stats(result)
    row = {
        "symbol": cfg.symbol,
        "name": cfg.symbol_name,
        "year": year,
        "ret_pct": float(metric(m, "total_return_pct")),
        "sharpe": float(metric(m, "sharpe_ratio")),
        "mdd_pct": float(metric(m, "max_drawdown_pct")),
        "closed_trade_count": float(metric(m, "closed_trade_count")),
        "metric_win_rate": float(metric(m, "win_rate")),
        "end_mv": float(metric(m, "end_market_value")),
        "n_bars": int(len(daily)),
        **ts,
    }
    return row


def main() -> None:
    rows = []
    for base in (KAICHENG, TIANTONG):
        for year in YEARS:
            print(f"run {base.symbol_name} {year} hold1-next-open ...", flush=True)
            rows.append(run_year(base, year))
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "metrics.csv", index=False)

    # 对照：同年仅止损（不止盈、不次日清）
    base_rows = []
    for base in (KAICHENG, TIANTONG):
        for year in YEARS:
            print(f"run {base.symbol_name} {year} stop_only ...", flush=True)
            cfg = replace(
                base,
                start_date=f"{year}0101",
                end_date=f"{year}1231",
                exit_next_open=False,
                take_profit_levels=None,
                ma_tp_enabled=False,
                factor4_enabled=False,
            )
            result, _ = run_open_break(cfg, show_report=False, verbose=False)
            m = result.metrics_df
            ts = _trade_stats(result)
            base_rows.append(
                {
                    "symbol": cfg.symbol,
                    "name": cfg.symbol_name,
                    "year": year,
                    "variant": "stop_only",
                    "ret_pct": float(metric(m, "total_return_pct")),
                    "sharpe": float(metric(m, "sharpe_ratio")),
                    "mdd_pct": float(metric(m, "max_drawdown_pct")),
                    "metric_win_rate": float(metric(m, "win_rate")),
                    **ts,
                }
            )
    base_df = pd.DataFrame(base_rows)
    base_df.to_csv(OUT / "stop_only_metrics.csv", index=False)

    report = f"""# 因子1：持股一日、次日开盘清（2025 / 2026）

规则：因子1 开盘突破买入（阴/小阳+禁双阳）；**下一交易日开盘全清**；不做止损/止盈拖延。
T+1：买入当日不可卖。本报告仅供研究，不构成投资建议。

## 次日开盘清

{df.to_markdown(index=False)}

## 对照：同年仅止损（可持有多日）

{base_df.to_markdown(index=False)}

## 解读

- `metric_win_rate` / `win_rate`：闭环交易胜率（%）。
- `avg_pnl_pct` / `med_pnl_pct`：单笔平均/中位毛收益（%）。
- `ret_pct`：账户累计收益%（含费用）。
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")
    (OUT / "manifest.json").write_text(
        json.dumps({"years": list(YEARS), "rule": "exit_next_open"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(report)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
