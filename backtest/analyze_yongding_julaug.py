"""永鼎股份 600105 · 7-8月策略回撤归因（一次性分析脚本）。"""
from __future__ import annotations

import logging
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

_MYQUAN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_MYQUAN))

import pandas as pd  # noqa: E402

from holdingStocks.watch_config import limit_down_pct_of, sina_of  # noqa: E402
from strategy import BacktestConfig, run_open_break_backtest  # noqa: E402
from strategy.data import fetch_daily  # noqa: E402

CODE = "600105"
NAME = "永鼎股份"
PCT = 0.03
PERIOD_START = "2026-07-01"
PERIOD_END = "2026-08-31"
CACHE = (
    Path(__file__).parent / "universe_zz500_1000" / "daily_cache" / "sh600105_daily_qfq.parquet"
)


def _to_day(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if t.tz is not None:
        t = t.tz_convert("Asia/Shanghai")
        t = pd.Timestamp(t.strftime("%Y-%m-%d"))
    return t.normalize()


def main() -> None:
    sym = sina_of(CODE)
    cfg = BacktestConfig(
        symbol=sym,
        symbol_name=NAME,
        em_symbol=CODE,
        threshold_pct=PCT,
        start_date="20250601",
        end_date="20260831",
        initial_cash=100_000.0,
        entry_ref="today_open",
        prev_entry_mode="yin_or_small_yang",
        limit_down_pct=limit_down_pct_of(CODE),
        daily_cache=CACHE,
        report_path=None,
    )
    daily = fetch_daily(sym, "20250601", "20260831", cache_path=CACHE)
    res = run_open_break_backtest(cfg, daily)

    eq = res.equity_curve_daily.astype(float).sort_index()
    eq.index = pd.to_datetime(eq.index).tz_localize(None).normalize()

    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    d = d.set_index("date").sort_index()
    seg = d.loc[PERIOD_START:PERIOD_END]
    if seg.empty:
        raise SystemExit("无 7-8 月行情")

    c0, c1 = float(seg["close"].iloc[0]), float(seg["close"].iloc[-1])
    hi, lo = float(seg["high"].max()), float(seg["low"].min())
    bh_ret = (c1 / c0 - 1.0) * 100.0

    eq_seg = eq.loc[PERIOD_START:PERIOD_END]
    eq0 = float(eq_seg.iloc[0])
    eq1 = float(eq_seg.iloc[-1])
    strat_ret = (eq1 / eq0 - 1.0) * 100.0
    peak = eq_seg.cummax()
    mdd = float((1.0 - eq_seg / peak).max() * 100.0)

    print(f"=== {NAME} {CODE} ±{PCT*100:.0f}% · {PERIOD_START} ~ {PERIOD_END} ===")
    print(f"数据最新收盘日: {seg.index[-1].date()}")
    print(f"股价: {c0:.2f} → {c1:.2f}  持有 {(c1/c0-1)*100:+.2f}%  区间高/低 {hi:.2f}/{lo:.2f}")
    print(f"策略: {eq0:.0f} → {eq1:.0f}  收益 {strat_ret:+.2f}%  区间最大回撤 {mdd:.2f}%")
    print()

    trades = getattr(res, "trades_df", pd.DataFrame())
    if trades is None or trades.empty:
        print("无闭环交易")
        return

    rows = []
    for i, r in trades.iterrows():
        et = r.get("entry_time")
        xt = r.get("exit_time")
        if pd.isna(et):
            continue
        et_d = _to_day(et)
        xt_d = _to_day(xt) if not pd.isna(xt) else None
        if xt_d is not None and xt_d < pd.Timestamp(PERIOD_START):
            continue
        if et_d > pd.Timestamp(PERIOD_END):
            continue
        ep = float(r.get("entry_price", float("nan")))
        xp = float(r.get("exit_price", float("nan"))) if xt_d is not None else float("nan")
        qty = float(r.get("quantity", float("nan")))
        pnl = float(r.get("net_pnl", float("nan"))) if not pd.isna(r.get("net_pnl")) else float("nan")
        ret = (xp / ep - 1.0) * 100.0 if ep > 0 and xp == xp else float("nan")
        rows.append(
            {
                "entry": str(et_d.date()),
                "exit": str(xt_d.date()) if xt_d is not None else "持仓中",
                "entry_px": round(ep, 2),
                "exit_px": round(xp, 2) if xp == xp else None,
                "qty": int(qty) if qty == qty else None,
                "trade_ret%": round(ret, 2) if ret == ret else None,
                "net_pnl": round(pnl, 2) if pnl == pnl else None,
            }
        )

    print("7-8 月相关交易（含跨月持仓）:")
    for t in rows:
        print(
            f"  买 {t['entry']} @{t['entry_px']} → 卖 {t['exit']} @{t['exit_px']} "
            f"| 单笔 {t['trade_ret%']}% | pnl {t['net_pnl']}"
        )

    print("\n逐日行情（7-8月）:")
    prev = None
    for day, r in seg.iterrows():
        o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
        chg = (c / prev - 1.0) * 100.0 if prev else 0.0
        stop = o * (1.0 - PCT)
        buy_trig = h >= o * (1.0 + PCT)
        stop_trig = l <= stop
        flag = []
        if chg <= -5:
            flag.append("大跌")
        if chg >= 5:
            flag.append("大涨")
        if stop_trig:
            flag.append("触止损带")
        if buy_trig:
            flag.append("触买带")
        print(
            f"  {day.date()} O{o:.2f} H{h:.2f} L{l:.2f} C{c:.2f} "
            f"{chg:+5.1f}% {'/'.join(flag)}"
        )
        prev = c


if __name__ == "__main__":
    main()
