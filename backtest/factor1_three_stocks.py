"""因子1 三标的多阈值回测：永杉锂业 / 华鲁恒升 / 东岳硅材。

口径：
- 仅因子1（开盘突破 ±pct，仅止损；不含因子2 注资）
- 阈值扫参：±2.0% / ±2.5% / ±3.0%
- 输出策略收益、买入持有收益、交易频次、利润因子、盈亏比

用法：
  cd backtest
  python factor1_three_stocks.py
  python factor1_three_stocks.py --force-refresh
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
import traceback
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy import BacktestConfig, run_open_break_backtest
from strategy.backtest import metric, monthly_returns_df, print_summary
from strategy.data import fetch_daily

logging.disable(logging.CRITICAL)

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "factor1_three_stocks"
CACHE_DIR = OUT_DIR / "daily_cache"
DETAIL_CSV = OUT_DIR / "detail.csv"
SUMMARY_CSV = OUT_DIR / "summary_best.csv"
SUMMARY_TXT = OUT_DIR / "summary.txt"
MONTHLY_DIR = OUT_DIR / "monthly"

START_DATE = "20200101"
INITIAL_CASH = 100_000.0
THRESHOLDS = (0.02, 0.025, 0.03)

STOCKS = [
    {"code": "603399", "name": "永杉锂业", "symbol": "sh603399"},
    {"code": "600426", "name": "华鲁恒升", "symbol": "sh600426"},
    {"code": "300821", "name": "东岳硅材", "symbol": "sz300821"},
]


def _bh_stats(daily: pd.DataFrame) -> tuple[float | None, float | None]:
    if daily is None or daily.empty or "close" not in daily.columns:
        return None, None
    closes = pd.to_numeric(daily["close"], errors="coerce").dropna()
    if closes.empty:
        return None, None
    c0, c1 = float(closes.iloc[0]), float(closes.iloc[-1])
    if c0 <= 0:
        return None, None
    bh_ret = (c1 / c0 - 1.0) * 100.0
    peak = closes.cummax()
    dd = (closes / peak - 1.0) * 100.0
    bh_dd = float(-dd.min()) if not dd.empty else None
    return bh_ret, bh_dd


def _trade_stats(result) -> dict[str, float | int | None]:
    """闭环交易：均盈/均亏/盈亏比、年均交易次数。"""
    out: dict[str, float | int | None] = {
        "avg_win_pct": None,
        "avg_loss_pct": None,
        "pl_ratio": None,
        "trades_per_year": None,
        "avg_hold_days": None,
    }
    td = getattr(result, "trades_df", None)
    if td is None or td.empty:
        return out

    pnl_col = next(
        (c for c in ("pnl", "realized_pnl", "profit") if c in td.columns),
        None,
    )
    ret_col = "return_pct" if "return_pct" in td.columns else None
    if pnl_col is None:
        return out

    pnls = pd.to_numeric(td[pnl_col], errors="coerce")
    wins = td.loc[pnls > 0]
    losses = td.loc[pnls <= 0]
    if ret_col is not None:
        aw = (
            float(pd.to_numeric(wins[ret_col], errors="coerce").mean())
            if len(wins)
            else float("nan")
        )
        al = (
            float(pd.to_numeric(losses[ret_col], errors="coerce").mean())
            if len(losses)
            else float("nan")
        )
    else:
        aw = float(pnls[pnls > 0].mean()) if (pnls > 0).any() else float("nan")
        al = float(pnls[pnls <= 0].mean()) if (pnls <= 0).any() else float("nan")

    out["avg_win_pct"] = None if aw != aw else round(aw, 4)
    out["avg_loss_pct"] = None if al != al else round(al, 4)
    if al == al and al != 0 and aw == aw:
        out["pl_ratio"] = round(abs(aw / al), 4)

    # 持有天数
    entry_col = next(
        (c for c in ("entry_time", "open_time", "start_time") if c in td.columns),
        None,
    )
    exit_col = next(
        (c for c in ("exit_time", "close_time", "end_time") if c in td.columns),
        None,
    )
    if entry_col and exit_col:
        et = pd.to_datetime(td[entry_col], errors="coerce")
        xt = pd.to_datetime(td[exit_col], errors="coerce")
        hold = (xt - et).dt.total_seconds() / 86400.0
        hold = hold.dropna()
        if not hold.empty:
            out["avg_hold_days"] = round(float(hold.mean()), 2)
            span_days = float((xt.max() - et.min()).total_seconds() / 86400.0)
            if span_days > 0:
                years = max(span_days / 365.25, 1e-9)
                out["trades_per_year"] = round(len(td) / years, 2)

    return out


def backtest_one(
    stock: dict,
    *,
    end_date: str,
    force_refresh: bool,
    verbose: bool,
) -> list[dict]:
    code = stock["code"]
    name = stock["name"]
    symbol = stock["symbol"]
    cache_path = CACHE_DIR / f"{symbol}_daily_qfq.parquet"
    rows: list[dict] = []

    try:
        daily = fetch_daily(
            symbol,
            START_DATE,
            end_date,
            cache_path=cache_path,
            force_refresh=force_refresh,
        )
    except TypeError:
        # 旧签名无 force_refresh
        daily = fetch_daily(
            symbol,
            START_DATE,
            end_date,
            cache_path=cache_path,
        )
    except Exception as e:  # noqa: BLE001
        for pct in THRESHOLDS:
            rows.append(
                {
                    "code": code,
                    "name": name,
                    "symbol": symbol,
                    "threshold_pct": pct,
                    "阈值%": round(pct * 100, 1),
                    "ok": 0,
                    "error": f"fetch: {type(e).__name__}: {e}",
                }
            )
        return rows

    if daily is None or daily.empty or len(daily) < 60:
        err = f"日线不足({0 if daily is None else len(daily)})"
        for pct in THRESHOLDS:
            rows.append(
                {
                    "code": code,
                    "name": name,
                    "symbol": symbol,
                    "threshold_pct": pct,
                    "阈值%": round(pct * 100, 1),
                    "ok": 0,
                    "error": err,
                    "n_bars": 0 if daily is None else int(len(daily)),
                }
            )
        return rows

    bh_ret, bh_dd = _bh_stats(daily)
    n_bars = int(len(daily))
    date0 = str(pd.to_datetime(daily["date"].iloc[0]).date())
    date1 = str(pd.to_datetime(daily["date"].iloc[-1]).date())

    for pct in THRESHOLDS:
        base: dict = {
            "code": code,
            "name": name,
            "symbol": symbol,
            "threshold_pct": pct,
            "阈值%": round(pct * 100, 1),
            "ok": 0,
            "error": "",
            "n_bars": n_bars,
            "start": date0,
            "end": date1,
            "bh_return_pct": bh_ret,
            "bh_max_drawdown_pct": bh_dd,
        }
        try:
            cfg = BacktestConfig(
                symbol=symbol,
                symbol_name=name,
                em_symbol=code,
                threshold_pct=pct,
                start_date=START_DATE,
                end_date=end_date,
                initial_cash=INITIAL_CASH,
                entry_ref="today_open",
                prev_entry_mode="yin_or_small_yang",
                daily_cache=cache_path,
                report_path=None,
            )
            result = run_open_break_backtest(cfg, daily)
            m = result.metrics_df
            strat = float(metric(m, "total_return_pct"))
            dd = float(metric(m, "max_drawdown_pct"))
            sharpe = float(metric(m, "sharpe_ratio"))
            win = float(metric(m, "win_rate"))
            n_tr = int(metric(m, "closed_trade_count"))
            pf = float(metric(m, "profit_factor"))
            end_mv = float(metric(m, "end_market_value"))
            tstats = _trade_stats(result)
            excess = None if bh_ret is None else strat - float(bh_ret)
            base.update(
                {
                    "total_return_pct": strat,
                    "max_drawdown_pct": dd,
                    "sharpe_ratio": sharpe,
                    "win_rate": win,
                    "closed_trade_count": n_tr,
                    "profit_factor": pf,
                    "pl_ratio": tstats["pl_ratio"],
                    "avg_win_pct": tstats["avg_win_pct"],
                    "avg_loss_pct": tstats["avg_loss_pct"],
                    "trades_per_year": tstats["trades_per_year"],
                    "avg_hold_days": tstats["avg_hold_days"],
                    "end_market_value": end_mv,
                    "excess_return_pct": excess,
                    "ok": 1,
                }
            )
            # 分月：策略 vs 持有
            monthly = monthly_returns_df(
                result, daily, initial_cash=INITIAL_CASH
            )
            if not monthly.empty:
                MONTHLY_DIR.mkdir(parents=True, exist_ok=True)
                mpath = MONTHLY_DIR / f"{name}_{pct*100:.1f}pct_monthly.csv"
                monthly.to_csv(mpath, index=False, encoding="utf-8-sig")
                base["monthly_csv"] = str(mpath.name)

            if verbose:
                print(f"\n===== {name} ±{pct*100:.1f}% =====")
                print_summary(
                    result,
                    daily,
                    symbol_name=name,
                    symbol=symbol,
                    initial_cash=INITIAL_CASH,
                    commission_rate=cfg.commission_rate,
                    stamp_tax_rate=cfg.stamp_tax_rate,
                    slippage_value=cfg.slippage_value,
                    misc_fee_rate=cfg.misc_fee_rate,
                    entry_pct=pct,
                    stop_pct=pct,
                )
                print(
                    f"盈亏比(均盈/|均亏|): {tstats['pl_ratio']}  "
                    f"利润因子: {pf:.4f}  "
                    f"年均闭环: {tstats['trades_per_year']}  "
                    f"平均持仓天: {tstats['avg_hold_days']}"
                )
                print(
                    f"策略收益%: {strat:.2f}  持有收益%: "
                    f"{bh_ret:.2f}  超额%: {excess:.2f}"
                    if excess is not None and bh_ret is not None
                    else f"策略收益%: {strat:.2f}"
                )
        except Exception as e:  # noqa: BLE001
            base["error"] = f"{type(e).__name__}: {e}"
            base["traceback"] = traceback.format_exc()[-800:]
            if verbose:
                print(f"[FAIL] {name} ±{pct*100:.1f}%: {base['error']}")
        rows.append(base)
    return rows


def _pick_best(df: pd.DataFrame) -> pd.DataFrame:
    ok = df[df["ok"] == 1].copy()
    if ok.empty:
        return ok
    # 优先超额，其次夏普，再次累计收益
    ok["rank_score"] = (
        ok["excess_return_pct"].fillna(-1e9)
        + 0.01 * ok["sharpe_ratio"].fillna(0)
        + 0.0001 * ok["total_return_pct"].fillna(0)
    )
    idx = ok.groupby("code")["rank_score"].idxmax()
    return ok.loc[idx].drop(columns=["rank_score"]).sort_values("code")


def _write_summary_txt(detail: pd.DataFrame, best: pd.DataFrame) -> None:
    lines: list[str] = []
    lines.append("# 因子1 三标的多阈值回测摘要")
    lines.append("")
    lines.append(f"- 区间起点: {START_DATE}")
    lines.append(f"- 阈值: {', '.join(f'±{p*100:.1f}%' for p in THRESHOLDS)}")
    lines.append("- 规则: 开盘突破买入 + 仅止损；前日阴/小阳；禁双阳跨日≥5%；T+1")
    lines.append("- 不含因子2 注资")
    lines.append("- 盈亏比 = 平均盈利回报% / |平均亏损回报%|；利润因子来自引擎 profit_factor")
    lines.append("")
    lines.append("## 全阈值明细")
    cols = [
        "name",
        "阈值%",
        "total_return_pct",
        "bh_return_pct",
        "excess_return_pct",
        "max_drawdown_pct",
        "sharpe_ratio",
        "win_rate",
        "closed_trade_count",
        "trades_per_year",
        "avg_hold_days",
        "profit_factor",
        "pl_ratio",
        "ok",
        "error",
    ]
    show = [c for c in cols if c in detail.columns]
    lines.append(detail[show].to_string(index=False))
    lines.append("")
    lines.append("## 每标的最优阈值（按超额优先）")
    if best.empty:
        lines.append("(无成功结果)")
    else:
        lines.append(best[show].to_string(index=False))
    SUMMARY_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="因子1 三标的多阈值回测")
    parser.add_argument("--force-refresh", action="store_true", help="忽略日线缓存重拉")
    parser.add_argument("--quiet", action="store_true", help="少打印摘要")
    parser.add_argument(
        "--end",
        default=dt.date.today().strftime("%Y%m%d"),
        help="结束日期 YYYYMMDD",
    )
    args = parser.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MONTHLY_DIR.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []
    for stock in STOCKS:
        print(f"\n>>> {stock['name']} ({stock['symbol']})")
        all_rows.extend(
            backtest_one(
                stock,
                end_date=args.end,
                force_refresh=bool(args.force_refresh),
                verbose=not bool(args.quiet),
            )
        )

    detail = pd.DataFrame(all_rows)
    detail.to_csv(DETAIL_CSV, index=False, encoding="utf-8-sig")
    best = _pick_best(detail)
    if not best.empty:
        best.to_csv(SUMMARY_CSV, index=False, encoding="utf-8-sig")
    _write_summary_txt(detail, best)

    print("\n========== 汇总 ==========")
    cols = [
        "name",
        "阈值%",
        "total_return_pct",
        "bh_return_pct",
        "excess_return_pct",
        "max_drawdown_pct",
        "sharpe_ratio",
        "win_rate",
        "closed_trade_count",
        "trades_per_year",
        "avg_hold_days",
        "profit_factor",
        "pl_ratio",
        "ok",
    ]
    show = [c for c in cols if c in detail.columns]
    print(detail[show].to_string(index=False))
    print(f"\n明细: {DETAIL_CSV}")
    print(f"最优: {SUMMARY_CSV}")
    print(f"摘要: {SUMMARY_TXT}")
    return 0 if (detail["ok"] == 1).any() else 1


if __name__ == "__main__":
    raise SystemExit(main())
