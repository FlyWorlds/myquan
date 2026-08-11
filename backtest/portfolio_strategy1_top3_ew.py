"""策略一 · 因子1 · 三票等权组合（独立账户合成）。

口径（对齐 kaicheng_tiantong_half）：
  · 默认取拟合池夏普 Top3，各跑独立策略一·因子1（各 10 万）
  · 组合净值 = 等权平均归一权益 × 总名义本金
  · 每日持仓状态 = 各票独立持仓拼接

用法：
  cd backtest
  python portfolio_strategy1_top3_ew.py
  python portfolio_strategy1_top3_ew.py --codes 600552,600330,601208
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
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
    _FIT_WATCH,
    _WATCH_PCT,
    limit_down_pct_of,
    sina_of,
)
from strategy import BacktestConfig, run_open_break_backtest  # noqa: E402
from strategy.backtest import metric  # noqa: E402
from strategy.data import fetch_daily  # noqa: E402
from strategy.open_break import DEFAULT_PCT  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "portfolio_s1_top3_ew"
CACHE_DIR = Path(__file__).resolve().parent / "universe_zz500_1000" / "daily_cache"
START = "20200101"
CASH_EACH = 100_000.0


def _pick_top3(*, min_bars: int = 1500) -> list[tuple[str, str, float]]:
    """默认取拟合池夏普 Top3，且要求日线足够覆盖 2020 至今（排除新股）。"""
    fit = Path(__file__).parent / "universe_zz500_1000" / "fit_sharpe1_excess.csv"
    if fit.exists():
        df = pd.read_csv(fit, dtype={"code": str})
        df["code"] = df["code"].astype(str).str.zfill(6)
        if "n_bars" in df.columns:
            long_hist = df[df["n_bars"].astype(float) >= float(min_bars)]
            if len(long_hist) >= 3:
                df = long_hist
        df = df.sort_values("sharpe_ratio", ascending=False).head(3)
        out = []
        for _, r in df.iterrows():
            code = str(r["code"]).zfill(6)
            out.append((code, str(r["name"]), float(r["threshold_pct"])))
        return out
    # fallback: watch 前三
    rows = []
    for code, name in _FIT_WATCH[:3]:
        c = str(code).zfill(6)
        rows.append((c, name, float(_WATCH_PCT.get(c, DEFAULT_PCT))))
    return rows


def _strip_tz_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(pd.to_datetime(idx))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return idx.normalize()


def _normalize_eq(eq: pd.Series) -> pd.Series:
    s = eq.astype(float).sort_index()
    s.index = _strip_tz_index(s.index)
    return s / float(s.iloc[0])


def _portfolio_metrics(eq: pd.Series) -> dict[str, Any]:
    eq = eq.dropna().astype(float).sort_index()
    tot = float(eq.iloc[-1] / eq.iloc[0] - 1.0)
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    ann = (1.0 + tot) ** (1.0 / years) - 1.0
    peak = eq.cummax()
    dd = 1.0 - eq / peak
    mdd = float(dd.max())
    mdd_i = dd.idxmax()
    rets = eq.pct_change().dropna()
    vol = float(rets.std() * (252**0.5)) if len(rets) else 0.0
    sharpe = float(ann / vol) if vol > 1e-12 else 0.0
    return {
        "start": str(eq.index[0].date()),
        "end": str(eq.index[-1].date()),
        "years": round(years, 2),
        "total_return_pct": round(tot * 100, 2),
        "annualized_return_pct": round(ann * 100, 2),
        "max_drawdown_pct": round(mdd * 100, 2),
        "max_drawdown_date": str(pd.Timestamp(mdd_i).date()),
        "end_equity": round(float(eq.iloc[-1]), 2),
        "volatility_pct": round(vol * 100, 2),
        "sharpe": round(sharpe, 3),
    }


def _yearly(port: pd.Series, bh: pd.Series) -> pd.DataFrame:
    def ye(s: pd.Series) -> pd.Series:
        return s.groupby(s.index.year).apply(lambda x: float(x.iloc[-1]))

    def ydd(s: pd.Series) -> dict[int, float]:
        return {
            int(yr): float((1.0 - part / part.cummax()).max()) * 100.0
            for yr, part in s.groupby(s.index.year)
        }

    pe, be = ye(port), ye(bh)
    yds, ydb = ydd(port), ydd(bh)
    prev_p, prev_b = float(port.iloc[0]), float(bh.iloc[0])
    rows = []
    for yr in sorted(int(x) for x in pe.index):
        p1, b1 = float(pe.loc[yr]), float(be.loc[yr])
        rs, rb = p1 / prev_p - 1.0, b1 / prev_b - 1.0
        rows.append(
            {
                "年份": yr,
                "组合策略%": round(rs * 100, 2),
                "等权持有%": round(rb * 100, 2),
                "超额%": round((rs - rb) * 100, 2),
                "策略回撤%": round(yds.get(yr, 0.0), 2),
                "持有回撤%": round(ydb.get(yr, 0.0), 2),
            }
        )
        prev_p, prev_b = p1, b1
    return pd.DataFrame(rows)


def _to_naive_day(ts: Any) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if getattr(t, "tz", None) is not None:
        t = t.tz_convert("Asia/Shanghai")
        t = pd.Timestamp(t.strftime("%Y-%m-%d"))
    return pd.Timestamp(t).normalize()


def _holding_flags_from_trades(
    trades: pd.DataFrame, daily_index: pd.DatetimeIndex, symbol: str
) -> pd.Series:
    """用闭环交易的 entry_time~exit_time（含首尾）还原每日是否持仓。"""
    held = pd.Series(False, index=daily_index)
    if trades is None or trades.empty:
        return held
    t = trades.copy()
    # akquant trades_df: 每行一笔 Long 闭环（entry_time / exit_time）
    if "entry_time" in t.columns and "exit_time" in t.columns:
        for _, r in t.iterrows():
            if pd.isna(r["entry_time"]):
                continue
            d0 = _to_naive_day(r["entry_time"])
            d1 = _to_naive_day(r["exit_time"]) if not pd.isna(r["exit_time"]) else daily_index[-1]
            mask = (daily_index >= d0) & (daily_index <= d1)
            held.loc[mask] = True
        return held

    # 兼容逐笔成交
    side_col = next((c for c in ("side", "direction", "action") if c in t.columns), None)
    ts_col = next(
        (c for c in ("timestamp", "time", "datetime", "date", "created_at") if c in t.columns),
        None,
    )
    if side_col is None or ts_col is None:
        return held
    events: list[tuple[pd.Timestamp, bool]] = []
    for _, r in t.iterrows():
        side = str(r[side_col]).lower()
        day = _to_naive_day(r[ts_col])
        if "buy" in side or side in ("b", "long", "买入"):
            events.append((day, True))
        elif "sell" in side or side in ("s", "short", "卖出"):
            events.append((day, False))
    events.sort(key=lambda x: x[0])
    state = False
    ev_i = 0
    for day in daily_index:
        while ev_i < len(events) and events[ev_i][0] <= day:
            state = events[ev_i][1]
            ev_i += 1
        held.loc[day] = state
    return held


def _holding_flags_from_positions(positions: Any, daily_index: pd.DatetimeIndex) -> pd.Series | None:
    if positions is None:
        return None
    try:
        if isinstance(positions, pd.DataFrame) and "long_shares" in positions.columns:
            p = positions.copy()
            if "date" in p.columns:
                days = pd.to_datetime(p["date"])
            else:
                days = pd.to_datetime(p.index)
            if getattr(days, "dt", None) is not None and getattr(days.dt, "tz", None) is not None:
                days = days.dt.tz_localize(None)
            elif getattr(days, "tz", None) is not None:
                days = days.tz_localize(None)
            days = pd.DatetimeIndex(days).normalize()
            s = pd.Series(pd.to_numeric(p["long_shares"], errors="coerce").fillna(0).values > 0, index=days)
            return s.groupby(level=0).any().reindex(daily_index).fillna(False)
        if isinstance(positions, pd.DataFrame) and positions.shape[1] >= 1:
            # 形如 index=datetime, columns=symbol, values=shares
            idx = pd.to_datetime(positions.index)
            if getattr(idx, "tz", None) is not None:
                idx = idx.tz_localize(None)
            idx = pd.DatetimeIndex(idx).normalize()
            shares = positions.iloc[:, 0].astype(float)
            s = pd.Series(shares.values > 0, index=idx)
            return s.groupby(level=0).any().reindex(daily_index).fillna(False)
    except Exception:
        return None
    return None


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
    eq.index = pd.to_datetime(eq.index)
    if getattr(eq.index, "tz", None) is not None:
        eq.index = eq.index.tz_localize(None)
    eq.index = pd.DatetimeIndex(eq.index).normalize()
    eq = eq.sort_index().astype(float)
    # BH
    d = daily.copy()
    dates = pd.to_datetime(d["date"])
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_localize(None)
    d["date"] = dates.dt.normalize()
    d = d.set_index("date").sort_index()
    bh = d["close"].astype(float).reindex(eq.index).ffill()
    bh = bh / float(bh.dropna().iloc[0]) * CASH_EACH
    m = result.metrics_df
    trades = getattr(result, "trades_df", None)
    if trades is None:
        trades = getattr(result, "orders_df", pd.DataFrame())
    if not isinstance(trades, pd.DataFrame):
        trades = pd.DataFrame()
    held = _holding_flags_from_trades(trades, eq.index, symbol)
    if not bool(held.any()):
        alt = _holding_flags_from_positions(getattr(result, "positions", None), eq.index)
        if alt is not None:
            held = alt
    # 导出用：把闭环拆成买入/卖出事件
    trade_events = []
    if not trades.empty and "entry_time" in trades.columns:
        for _, r in trades.iterrows():
            trade_events.append(
                {
                    "code": code,
                    "name": name,
                    "side": "buy",
                    "date": str(_to_naive_day(r["entry_time"]).date()),
                    "price": float(r.get("entry_price", float("nan"))),
                    "qty": float(r.get("quantity", float("nan"))),
                    "pnl": None,
                }
            )
            if not pd.isna(r.get("exit_time")):
                trade_events.append(
                    {
                        "code": code,
                        "name": name,
                        "side": "sell",
                        "date": str(_to_naive_day(r["exit_time"]).date()),
                        "price": float(r.get("exit_price", float("nan"))),
                        "qty": float(r.get("quantity", float("nan"))),
                        "pnl": float(r.get("net_pnl", float("nan"))),
                    }
                )
    return {
        "code": code,
        "name": name,
        "pct": pct,
        "equity": eq,
        "bh": bh,
        "held": held,
        "trades": trades,
        "trade_events": trade_events,
        "total_return_pct": float(metric(m, "total_return_pct")),
        "max_drawdown_pct": float(metric(m, "max_drawdown_pct")),
        "sharpe": float(metric(m, "sharpe_ratio")),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--codes",
        default="",
        help="逗号分隔代码；默认取拟合夏普 Top3",
    )
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    end = dt.date.today().strftime("%Y%m%d")

    if args.codes.strip():
        codes = [c.strip().zfill(6) for c in args.codes.split(",") if c.strip()]
        name_map = {str(a).zfill(6): b for a, b in _FIT_WATCH}
        picks = [
            (c, name_map.get(c, c), float(_WATCH_PCT.get(c, DEFAULT_PCT))) for c in codes
        ]
    else:
        picks = _pick_top3()

    print("三票等权组合 · 策略一因子1")
    print("标的:", ", ".join(f"{c} {n} ±{p*100:.1f}%" for c, n, p in picks))

    legs: list[dict[str, Any]] = []
    for code, name, pct in picks:
        print(f"  回测 {code} {name} …", flush=True)
        legs.append(_run_one(code, name, pct, end))

    # 对齐日期
    idx = legs[0]["equity"].index
    for leg in legs[1:]:
        idx = idx.intersection(leg["equity"].index)
    idx = idx.sort_values()

    norms = [_normalize_eq(leg["equity"].reindex(idx).ffill()) for leg in legs]
    port_nav = sum(norms) / len(norms)
    port_eq = port_nav * (CASH_EACH * len(legs))

    bh_norms = []
    for leg in legs:
        b = leg["bh"].reindex(idx).ffill()
        bh_norms.append(b / float(b.iloc[0]))
    bh_nav = sum(bh_norms) / len(bh_norms)
    bh_eq = bh_nav * (CASH_EACH * len(legs))

    pm = _portfolio_metrics(port_eq)
    bm = _portfolio_metrics(bh_eq)
    yearly = _yearly(port_eq, bh_eq)

    # 每日持仓状态
    rows = []
    for day in idx:
        held_names = []
        held_codes = []
        entered = []
        exited = []
        for leg in legs:
            on = bool(leg["held"].reindex(idx).ffill().loc[day])
            # 进出：与昨日比较
            prev_days = idx[idx < day]
            prev_on = False
            if len(prev_days):
                prev_on = bool(leg["held"].reindex(idx).ffill().loc[prev_days[-1]])
            if on:
                held_codes.append(leg["code"])
                held_names.append(leg["name"])
            if on and not prev_on:
                entered.append(f"{leg['code']}{leg['name']}")
            if (not on) and prev_on:
                exited.append(f"{leg['code']}{leg['name']}")
        rows.append(
            {
                "date": day.date().isoformat(),
                "n_hold": len(held_codes),
                "codes": "|".join(held_codes),
                "names": "|".join(held_names),
                "entered": "|".join(entered),
                "exited": "|".join(exited),
                "equity": round(float(port_eq.loc[day]), 2),
                "bh_equity": round(float(bh_eq.loc[day]), 2),
            }
        )
    daily = pd.DataFrame(rows)

    # 导出
    daily.to_csv(OUT_DIR / "daily_holdings.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(OUT_DIR / "yearly.csv", index=False, encoding="utf-8-sig")
    events = pd.DataFrame([e for leg in legs for e in leg.get("trade_events", [])])
    if not events.empty:
        events = events.sort_values(["date", "code", "side"])
        events.to_csv(OUT_DIR / "trades.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        {
            "date": idx,
            "strategy": port_eq.values,
            "bh_equal": bh_eq.values,
        }
    ).to_csv(OUT_DIR / "equity.csv", index=False, encoding="utf-8-sig")

    leg_lines = []
    for leg in legs:
        leg_lines.append(
            f"  {leg['code']} {leg['name']} ±{leg['pct']*100:.1f}% | "
            f"策略{leg['total_return_pct']:+.1f}% 回撤{leg['max_drawdown_pct']:.1f}% "
            f"夏普{leg['sharpe']:.3f}"
        )

    # 进出样本：有 entered/exited 的日子
    moves = daily[(daily["entered"].astype(str).str.len() > 0) | (daily["exited"].astype(str).str.len() > 0)]
    recent_moves = moves.tail(25)
    recent_hold = daily.tail(15)

    excess = pm["total_return_pct"] - bm["total_return_pct"]
    lines = [
        f"生成时间: {dt.datetime.now():%Y-%m-%d %H:%M:%S}",
        "策略: 策略一 · 因子1",
        "组合口径: 三票等权独立账户合成（各 10 万 → 总名义 30 万）",
        "选股: 拟合池夏普≥1且超额>0，且 n_bars≥1500（覆盖约 2020 至今），取夏普 Top3",
        "标的:",
        *leg_lines,
        f"区间: {pm['start']} → {pm['end']}（约 {pm['years']} 年）",
        "",
        "=== 组合绩效 ===",
        f"总收益率: {pm['total_return_pct']:+.2f}%",
        f"年化收益: {pm['annualized_return_pct']:+.2f}%",
        f"最大回撤: {pm['max_drawdown_pct']:.2f}% @ {pm['max_drawdown_date']}",
        f"夏普: {pm['sharpe']:.3f}  波动: {pm['volatility_pct']:.2f}%",
        f"期末权益: {pm['end_equity']:,.2f}",
        "",
        "=== 三票等权买入持有 ===",
        f"总收益率: {bm['total_return_pct']:+.2f}%",
        f"年化收益: {bm['annualized_return_pct']:+.2f}%",
        f"最大回撤: {bm['max_drawdown_pct']:.2f}%",
        f"超额（策略-持有）: {excess:+.2f}%",
        "",
        "=== 分年 ===",
        yearly.to_string(index=False),
        "",
        f"持仓日占比: {(daily['n_hold']>0).mean()*100:.1f}%  平均持仓数: {daily['n_hold'].mean():.2f}",
        f"买入次数: {int((events['side']=='buy').sum()) if not events.empty else 0}  "
        f"卖出次数: {int((events['side']=='sell').sum()) if not events.empty else 0}",
        "",
        "=== 最近持仓（15 日）===",
        recent_hold[["date", "n_hold", "names", "entered", "exited", "equity"]].to_string(
            index=False
        ),
        "",
        "=== 最近进出（25 条）===",
        recent_moves[["date", "n_hold", "names", "entered", "exited"]].to_string(index=False)
        if not recent_moves.empty
        else "(无)",
        "",
        f"明细: {OUT_DIR}",
    ]

    text = "\n".join(lines) + "\n"
    (OUT_DIR / "summary.txt").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
