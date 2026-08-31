"""策略一 · 全池等权组合 · 区间/单月收益。

用法:
  python portfolio_s1_pool_aug.py --month 2026-08
  python portfolio_s1_pool_aug.py --from 2026-07 --to 2026-08-31
  python portfolio_s1_pool_aug.py --from 2026-07-01
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import warnings
from pathlib import Path
from typing import Any

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

import pandas as pd  # noqa: E402

from holdingStocks.watch_config import (  # noqa: E402
    WATCHLIST,
    limit_down_pct_of,
    sina_of,
)
from strategy import BacktestConfig, run_open_break_backtest  # noqa: E402
from strategy.data import _latest_completed_weekday, fetch_daily  # noqa: E402
from strategy.open_break import DEFAULT_PCT  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "portfolio_s1_pool_aug"
CACHE_DIR = Path(__file__).resolve().parent / "universe_zz500_1000" / "daily_cache"
START = "20200101"
CASH_EACH = 100_000.0


def _strip_tz_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(pd.to_datetime(idx))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return idx.normalize()


def _normalize_eq(eq: pd.Series) -> pd.Series:
    s = eq.astype(float).sort_index()
    s.index = _strip_tz_index(s.index)
    return s / float(s.iloc[0])


def _parse_from(s: str) -> pd.Timestamp:
    s = s.strip()
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return pd.Timestamp(f"{s}-01")
    return pd.Timestamp(s)


def _parse_to(s: str) -> pd.Timestamp:
    s = s.strip()
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return pd.Timestamp(s) + pd.offsets.MonthEnd(0)
    return pd.Timestamp(s)


def _period_slice(s: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    s = s.dropna().astype(float).sort_index()
    s.index = _strip_tz_index(s.index)
    part = s[(s.index >= start.normalize()) & (s.index <= end.normalize())]
    if part.empty:
        return part
    return part / float(part.iloc[0])


def _period_return(s: pd.Series) -> float | None:
    if s.empty:
        return None
    return float(s.iloc[-1] / s.iloc[0] - 1.0) * 100.0


def _run_one(code: str, name: str, pct: float, end: str) -> dict[str, Any]:
    symbol = sina_of(code)
    cache = CACHE_DIR / f"{symbol}_daily_qfq.parquet"
    cfg = BacktestConfig(
        symbol=symbol,
        symbol_name=name,
        em_symbol=code,
        threshold_pct=pct,
        start_date=START,
        end_date=end,
        initial_cash=CASH_EACH,
        entry_ref="today_open",
        prev_entry_mode="yin_or_small_yang",
        limit_down_pct=limit_down_pct_of(code),
        daily_cache=cache,
        report_path=None,
    )
    daily = fetch_daily(symbol, START, end, cache_path=cache)
    result = run_open_break_backtest(cfg, daily)
    eq = result.equity_curve_daily.copy()
    if not isinstance(eq, pd.Series):
        eq = pd.Series(eq)
    eq.index = _strip_tz_index(pd.DatetimeIndex(pd.to_datetime(eq.index)))
    eq = eq.sort_index().astype(float)

    d = daily.copy()
    dates = pd.to_datetime(d["date"])
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_localize(None)
    d["date"] = dates.dt.normalize()
    d = d.set_index("date").sort_index()
    bh = d["close"].astype(float).reindex(eq.index).ffill()
    bh = bh / float(bh.dropna().iloc[0]) * CASH_EACH
    return {"code": code, "name": name, "pct": pct, "equity": eq, "bh": bh}


def _build_portfolio(legs: list[dict[str, Any]]) -> tuple[pd.Series, pd.Series, pd.DatetimeIndex]:
    idx = legs[0]["equity"].index
    for leg in legs[1:]:
        idx = idx.intersection(leg["equity"].index)
    idx = idx.sort_values()
    port_norms = [_normalize_eq(leg["equity"].reindex(idx).ffill()) for leg in legs]
    bh_norms = []
    for leg in legs:
        b = leg["bh"].reindex(idx).ffill()
        bh_norms.append(b / float(b.iloc[0]))
    port_nav = sum(port_norms) / len(port_norms)
    bh_nav = sum(bh_norms) / len(bh_norms)
    return port_nav, bh_nav, idx


def _stock_rows(
    legs: list[dict[str, Any]],
    idx: pd.DatetimeIndex,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for leg in legs:
        eq0 = _normalize_eq(leg["equity"].reindex(idx).ffill())
        bh0 = leg["bh"].reindex(idx).ffill()
        bh0 = bh0 / float(bh0.iloc[0])
        s_eq = _period_slice(eq0, start, end)
        s_bh = _period_slice(bh0, start, end)
        if s_eq.empty:
            continue
        sr = _period_return(s_eq) or 0.0
        br = _period_return(s_bh) or 0.0
        rows.append(
            {
                "code": leg["code"],
                "name": leg["name"],
                "threshold_pct": round(leg["pct"] * 100, 1),
                "strategy_pct": round(sr, 2),
                "bh_pct": round(br, 2),
                "excess_pct": round(sr - br, 2),
            }
        )
    rows.sort(key=lambda r: r["strategy_pct"], reverse=True)
    return rows


def _monthly_breakdown(port_nav: pd.Series, bh_nav: pd.Series) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    months = sorted({(d.year, d.month) for d in port_nav.index})
    for year, month in months:
        m_start = pd.Timestamp(year=year, month=month, day=1)
        m_end = m_start + pd.offsets.MonthEnd(0)
        p = _period_slice(port_nav, m_start, m_end)
        b = _period_slice(bh_nav, m_start, m_end)
        if p.empty:
            continue
        pr = _period_return(p) or 0.0
        br = _period_return(b) or 0.0
        out.append(
            {
                "month": f"{year}-{month:02d}",
                "start": str(p.index[0].date()),
                "end": str(p.index[-1].date()),
                "n_trading_days": len(p),
                "portfolio_strategy_pct": round(pr, 2),
                "portfolio_bh_pct": round(br, 2),
                "excess_pct": round(pr - br, 2),
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default="", help="单月 YYYY-MM（与 --from 二选一）")
    ap.add_argument("--from", dest="from_date", default="", help="区间起点 YYYY-MM 或 YYYY-MM-DD")
    ap.add_argument("--to", dest="to_date", default="", help="区间终点，默认最近已收盘日")
    ap.add_argument("--end", default="", help="回测拉数截止 YYYYMMDD，默认今天")
    args = ap.parse_args()

    latest = pd.Timestamp(_latest_completed_weekday())
    if args.month.strip():
        year_s, month_s = args.month.split("-", 1)
        period_start = pd.Timestamp(f"{year_s}-{month_s}-01")
        period_end = period_start + pd.offsets.MonthEnd(0)
        label = f"{year_s}-{month_s}"
        out_name = f"summary_{year_s}{month_s}"
    elif args.from_date.strip():
        period_start = _parse_from(args.from_date)
        period_end = _parse_to(args.to_date) if args.to_date.strip() else latest
        label = f"{period_start.date()} → {period_end.date()}"
        out_name = f"summary_{period_start:%Y%m%d}_{period_end:%Y%m%d}"
    else:
        period_start = pd.Timestamp("2026-08-01")
        period_end = pd.Timestamp("2026-08-31")
        label = "2026-08"
        out_name = "summary_202608"

    end_fetch = args.end.strip() or latest.strftime("%Y%m%d")
    period_end = min(period_end, latest)

    picks = [
        (
            str(w["code"]).zfill(6),
            str(w["name"]),
            float(w.get("entry_pct", w.get("pct", DEFAULT_PCT))),
        )
        for w in WATCHLIST
    ]

    print(f"策略一全池等权 · {label} · {len(picks)} 只 · 数据至 {period_end.date()}")
    legs: list[dict[str, Any]] = []
    for code, name, pct in picks:
        print(f"  {code} {name} ±{pct*100:.1f}%", flush=True)
        legs.append(_run_one(code, name, pct, end_fetch))

    port_nav, bh_nav, idx = _build_portfolio(legs)
    port_p = _period_slice(port_nav, period_start, period_end)
    bh_p = _period_slice(bh_nav, period_start, period_end)
    if port_p.empty:
        raise SystemExit(f"区间无交易日: {period_start.date()} ~ {period_end.date()}")

    port_ret = _period_return(port_p) or 0.0
    bh_ret = _period_return(bh_p) or 0.0
    stock_rows = _stock_rows(legs, idx, period_start, period_end)
    monthly = _monthly_breakdown(port_p, bh_p)

    daily_rows = [
        {
            "date": day.strftime("%Y-%m-%d"),
            "strategy_nav": round(float(port_p.loc[day]) * 100, 2),
            "bh_nav": round(float(bh_p.loc[day]) * 100, 2),
        }
        for day in port_p.index
    ]

    data_last = max(_strip_tz_index(leg["equity"].index).max() for leg in legs)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "label": label,
        "period_start": str(period_start.date()),
        "period_end": str(period_end.date()),
        "data_last_date": str(data_last.date()),
        "start": str(port_p.index[0].date()),
        "end": str(port_p.index[-1].date()),
        "n_stocks": len(picks),
        "n_trading_days": len(port_p),
        "portfolio_strategy_pct": round(port_ret, 2),
        "portfolio_bh_pct": round(bh_ret, 2),
        "excess_pct": round(port_ret - bh_ret, 2),
        "pool_label": "策略一全池等权（沪深主板，剔科创/创业）",
        "monthly": monthly,
        "stocks": stock_rows,
        "daily": daily_rows,
    }
    out_path = OUT_DIR / f"{out_name}.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"\n区间 {port_p.index[0].date()} → {port_p.index[-1].date()} "
        f"({len(port_p)} 日) · 数据源最新 {data_last.date()}"
    )
    print(f"组合策略 {port_ret:+.2f}% | 等权持有 {bh_ret:+.2f}% | 超额 {port_ret - bh_ret:+.2f}%")
    for m in monthly:
        print(
            f"  {m['month']}: 策略 {m['portfolio_strategy_pct']:+.2f}% | "
            f"持有 {m['portfolio_bh_pct']:+.2f}% | 超额 {m['excess_pct']:+.2f}%"
        )
    print(f"写入 {out_path}")


if __name__ == "__main__":
    main()
