"""策略一 · 因子1 · 组合回测（最多持仓 3 只）。

标的池：holdingStocks/watch_config 拟合池（中证500+1000 剔科创，多阈值优选）
规则：开盘±pct 买入 / 仅止损卖 / T+1 / 前日阴或小阳 / 双阳跨日过滤
仓位：共享账户；空仓位时按当前权益的 1/3 开仓（手数取整）；同日多信号按夏普序（池序）优先

输出：
  backtest/portfolio_s1_top3/
    daily_holdings.csv   每日持仓与进出
    trades.csv           成交明细
    yearly.csv           分年收益/超额/回撤
    equity.csv           组合与等权持有净值
    summary.txt          摘要

用法：
  cd backtest
  python portfolio_strategy1_top3.py
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import sys
import warnings
from dataclasses import dataclass, field
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
    _FIT_WATCH,
    _WATCH_PCT,
    limit_down_pct_of,
    sina_of,
)
from strategy.data import fetch_daily  # noqa: E402
from strategy.open_break import (  # noqa: E402
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    DEFAULT_PCT,
    TICK_SIZE,
    entry_filters_ok,
    entry_trigger_price,
    limit_down_state,
    stop_trigger_price,
)

OUT_DIR = Path(__file__).resolve().parent / "portfolio_s1_top3"
CACHE_DIR = Path(__file__).resolve().parent / "universe_zz500_1000" / "daily_cache"

START_DATE = "20200101"
INITIAL_CASH = 300_000.0  # 3 槽位，名义每槽 10 万
MAX_POS = 3
LOT = 100
COMMISSION = 0.0000854
STAMP = 0.001
SLIP = 0.001


@dataclass
class Position:
    code: str
    name: str
    shares: int
    buy_date: pd.Timestamp
    buy_px: float
    pct: float


@dataclass
class PortfolioState:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    peak: float = 0.0


def _fee_buy(notional: float) -> float:
    return abs(notional) * COMMISSION


def _fee_sell(notional: float) -> float:
    return abs(notional) * (COMMISSION + STAMP)


def _slip_buy(px: float) -> float:
    return float(px) * (1.0 + SLIP)


def _slip_sell(px: float) -> float:
    return float(px) * (1.0 - SLIP)


def _mark_equity(state: PortfolioState, closes: dict[str, float]) -> float:
    eq = float(state.cash)
    for code, pos in state.positions.items():
        eq += pos.shares * float(closes.get(code, pos.buy_px))
    return eq


def load_panel() -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]], pd.DatetimeIndex]:
    """拉全池日线，对齐交易日索引。"""
    meta: list[dict[str, Any]] = []
    panels: dict[str, pd.DataFrame] = {}
    end = dt.date.today().strftime("%Y%m%d")
    for code, name in _FIT_WATCH:
        c = str(code).zfill(6)
        symbol = sina_of(c)
        pct = float(_WATCH_PCT.get(c, DEFAULT_PCT))
        cache = CACHE_DIR / f"{symbol}_daily_qfq.parquet"
        daily = fetch_daily(symbol, START_DATE, end, cache_path=cache)
        if daily is None or daily.empty or len(daily) < 60:
            print(f"  skip {c} {name}: 日线不足")
            continue
        df = daily.copy()
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
        df = (
            df.dropna(subset=["open", "high", "low", "close"])
            .sort_values("date")
            .drop_duplicates("date")
            .set_index("date")
        )
        panels[c] = df
        meta.append(
            {
                "code": c,
                "name": name,
                "symbol": symbol,
                "pct": pct,
                "limit_down_pct": limit_down_pct_of(c),
            }
        )
        print(f"  loaded {c} {name} ±{pct*100:.1f}% bars={len(df)}")

    # 交易日 = 并集（用上证/多数股票日期）；取任意一只最长序列不够稳，用并集再要求至少有数据
    all_idx = sorted({d for df in panels.values() for d in df.index})
    idx = pd.DatetimeIndex(all_idx)
    return panels, meta, idx


def _bar(df: pd.DataFrame, day: pd.Timestamp) -> pd.Series | None:
    if day not in df.index:
        return None
    return df.loc[day]


def _prev_bars(
    df: pd.DataFrame, day: pd.Timestamp
) -> tuple[pd.Series | None, pd.Series | None]:
    hist = df.loc[df.index < day]
    if hist.empty:
        return None, None
    prev = hist.iloc[-1]
    prev2 = hist.iloc[-2] if len(hist) >= 2 else None
    return prev, prev2


def run_portfolio(
    panels: dict[str, pd.DataFrame],
    meta: list[dict[str, Any]],
    calendar: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    meta_by = {m["code"]: m for m in meta}
    # 池序 = 买入优先级（夏普降序）
    order = [m["code"] for m in meta]

    state = PortfolioState(cash=INITIAL_CASH, peak=INITIAL_CASH)
    daily_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []

    for day in calendar:
        day = pd.Timestamp(day).normalize()
        closes: dict[str, float] = {}
        for code in order:
            b = _bar(panels[code], day)
            if b is not None:
                closes[code] = float(b["close"])

        events: list[str] = []

        # ---- 1) 先处理持仓止损（T+1）----
        for code in list(state.positions.keys()):
            pos = state.positions[code]
            b = _bar(panels[code], day)
            if b is None:
                continue
            o, h, l, c = (
                float(b["open"]),
                float(b["high"]),
                float(b["low"]),
                float(b["close"]),
            )
            if o <= 0:
                continue
            if pos.buy_date.normalize() == day:
                continue  # T+1
            stop_px = stop_trigger_price(o, stop_pct=pos.pct, tick=TICK_SIZE)
            if l > stop_px + 1e-12:
                continue
            prev, _ = _prev_bars(panels[code], day)
            prev_close = float(prev["close"]) if prev is not None else None
            lim = limit_down_state(
                prev_close=prev_close,
                open_px=o,
                high_px=h,
                low_px=l,
                close_px=c,
                limit_down_pct=float(meta_by[code]["limit_down_pct"]),
                tick=TICK_SIZE,
            )
            if bool(lim["locked"]):
                events.append(f"止损封板未成交:{code}")
                continue
            exit_px = float(lim["limit_px"] if bool(lim["opened"]) else stop_px)
            fill = _slip_sell(exit_px)
            notional = pos.shares * fill
            fee = _fee_sell(notional)
            state.cash += notional - fee
            trade_rows.append(
                {
                    "date": day.date().isoformat(),
                    "side": "sell",
                    "code": code,
                    "name": pos.name,
                    "shares": pos.shares,
                    "price": round(fill, 4),
                    "notional": round(notional, 2),
                    "fee": round(fee, 2),
                    "reason": "止损",
                    "pct": pos.pct,
                }
            )
            events.append(f"卖出止损:{code}@{fill:.2f}×{pos.shares}")
            del state.positions[code]

        # ---- 2) 空槽买入（同日多信号按池序）----
        free = MAX_POS - len(state.positions)
        if free > 0:
            eq_now = _mark_equity(state, closes)
            # 每槽目标名义：当前权益 / MAX_POS
            slot_budget = eq_now / float(MAX_POS)
            for code in order:
                if free <= 0:
                    break
                if code in state.positions:
                    continue
                b = _bar(panels[code], day)
                if b is None:
                    continue
                o, h = float(b["open"]), float(b["high"])
                if o <= 0:
                    continue
                m = meta_by[code]
                pct = float(m["pct"])
                buy_px = entry_trigger_price(o, entry_pct=pct, tick=TICK_SIZE)
                if h + 1e-12 < buy_px:
                    continue
                prev, prev2 = _prev_bars(panels[code], day)
                if prev is None:
                    continue
                if not entry_filters_ok(
                    float(prev["open"]),
                    float(prev["close"]),
                    float(prev2["open"]) if prev2 is not None else None,
                    float(prev2["close"]) if prev2 is not None else None,
                    entry_pct=pct,
                    prev_entry_mode="yin_or_small_yang",
                    tick=TICK_SIZE,
                    ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
                    ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
                    double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
                    double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
                ):
                    continue
                fill = _slip_buy(buy_px)
                budget = min(slot_budget, state.cash * 0.995)
                shares = int(budget // (fill * LOT)) * LOT
                if shares < LOT:
                    continue
                notional = shares * fill
                fee = _fee_buy(notional)
                if notional + fee > state.cash + 1e-6:
                    shares = int((state.cash * 0.995) // (fill * LOT)) * LOT
                    if shares < LOT:
                        continue
                    notional = shares * fill
                    fee = _fee_buy(notional)
                state.cash -= notional + fee
                state.positions[code] = Position(
                    code=code,
                    name=str(m["name"]),
                    shares=shares,
                    buy_date=day,
                    buy_px=fill,
                    pct=pct,
                )
                trade_rows.append(
                    {
                        "date": day.date().isoformat(),
                        "side": "buy",
                        "code": code,
                        "name": m["name"],
                        "shares": shares,
                        "price": round(fill, 4),
                        "notional": round(notional, 2),
                        "fee": round(fee, 2),
                        "reason": "开盘突破买入",
                        "pct": pct,
                    }
                )
                events.append(f"买入:{code}@{fill:.2f}×{shares}")
                free -= 1
                # 买入后更新 closes 以便权益一致
                closes[code] = float(b["close"])

        # ---- 3) 日终盯市 ----
        # 补齐持仓收盘价（无行情用买价）
        for code, pos in state.positions.items():
            if code not in closes:
                closes[code] = pos.buy_px
        eq = _mark_equity(state, closes)
        state.peak = max(state.peak, eq)
        dd = 1.0 - eq / state.peak if state.peak > 0 else 0.0

        held_codes = list(state.positions.keys())
        held_names = [state.positions[c].name for c in held_codes]
        held_detail = [
            f"{c}({state.positions[c].name},{state.positions[c].shares})"
            for c in held_codes
        ]
        daily_rows.append(
            {
                "date": day.date().isoformat(),
                "n_hold": len(held_codes),
                "codes": "|".join(held_codes),
                "names": "|".join(held_names),
                "detail": "|".join(held_detail),
                "cash": round(state.cash, 2),
                "equity": round(eq, 2),
                "drawdown_pct": round(dd * 100.0, 3),
                "events": ";".join(events),
            }
        )
        equity_rows.append({"date": day, "strategy_equity": eq})

    daily_df = pd.DataFrame(daily_rows)
    trades_df = pd.DataFrame(trade_rows)
    eq_df = pd.DataFrame(equity_rows).set_index("date")["strategy_equity"].astype(float)

    # 等权买入持有：25 只池子等权（有行情才纳入当日）
    bh = _bh_equal_weight(panels, order, eq_df.index, INITIAL_CASH)
    yearly = _yearly_table(eq_df, bh)
    return daily_df, trades_df, yearly, pd.DataFrame(
        {"date": eq_df.index, "strategy": eq_df.values, "bh_equal": bh.reindex(eq_df.index).values}
    )


def _bh_equal_weight(
    panels: dict[str, pd.DataFrame],
    codes: list[str],
    idx: pd.DatetimeIndex,
    initial: float,
) -> pd.Series:
    """池内等权买入持有（每日按有行情成分等权，前收盘对齐）。"""
    closes = {}
    for code in codes:
        s = panels[code]["close"].astype(float)
        s.index = pd.DatetimeIndex(s.index).normalize()
        closes[code] = s.reindex(idx).ffill()
    mat = pd.DataFrame(closes)
    # 归一：第一日有效价为 1
    first = mat.apply(lambda col: col.dropna().iloc[0] if col.notna().any() else math.nan)
    norm = mat.divide(first, axis=1)
    # 每日等权：对非空成分取均值
    nav = norm.mean(axis=1, skipna=True)
    nav = nav / float(nav.dropna().iloc[0]) * float(initial)
    return nav.astype(float)


def _metrics(eq: pd.Series) -> dict[str, Any]:
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


def _yearly_table(port: pd.Series, bh: pd.Series) -> pd.DataFrame:
    def year_end(s: pd.Series) -> pd.Series:
        return s.groupby(s.index.year).apply(lambda x: float(x.iloc[-1]))

    def yearly_dd(s: pd.Series) -> dict[int, float]:
        out: dict[int, float] = {}
        for yr, part in s.groupby(s.index.year):
            out[int(yr)] = float((1.0 - part / part.cummax()).max()) * 100.0
        return out

    pe, be = year_end(port), year_end(bh.reindex(port.index).ffill())
    yds, ydb = yearly_dd(port), yearly_dd(bh.reindex(port.index).ffill())
    prev_p, prev_b = float(port.iloc[0]), float(bh.reindex(port.index).ffill().iloc[0])
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


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(
        f"策略一·因子1 组合回测 | 最多持仓 {MAX_POS} | "
        f"池 {len(_FIT_WATCH)} 只 | {START_DATE}→今 | 初始 {INITIAL_CASH:,.0f}"
    )
    print("加载日线…")
    panels, meta, calendar = load_panel()
    if len(meta) < MAX_POS:
        raise SystemExit("可用标的不足")

    print(f"开始模拟 {len(calendar)} 个交易日 × {len(meta)} 只…")
    daily_df, trades_df, yearly, equity_df = run_portfolio(panels, meta, calendar)

    eq = equity_df.set_index(pd.to_datetime(equity_df["date"]))["strategy"].astype(float)
    bh = equity_df.set_index(pd.to_datetime(equity_df["date"]))["bh_equal"].astype(float)
    pm = _metrics(eq)
    bm = _metrics(bh)
    excess = pm["total_return_pct"] - bm["total_return_pct"]

    daily_df.to_csv(OUT_DIR / "daily_holdings.csv", index=False, encoding="utf-8-sig")
    trades_df.to_csv(OUT_DIR / "trades.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(OUT_DIR / "yearly.csv", index=False, encoding="utf-8-sig")
    equity_df.to_csv(OUT_DIR / "equity.csv", index=False, encoding="utf-8-sig")

    # 持仓状态摘要：近期与换手
    n_buys = int((trades_df["side"] == "buy").sum()) if not trades_df.empty else 0
    n_sells = int((trades_df["side"] == "sell").sum()) if not trades_df.empty else 0
    avg_hold = float(daily_df["n_hold"].mean()) if not daily_df.empty else 0.0

    # 最近 20 个有事件的交易日 + 最近 10 日持仓
    recent_events = daily_df[daily_df["events"].astype(str).str.len() > 0].tail(30)
    recent_hold = daily_df.tail(15)

    lines = [
        f"生成时间: {dt.datetime.now():%Y-%m-%d %H:%M:%S}",
        "策略: 策略一 · 因子1（开盘突破仅止损）",
        f"组合: 最多同时持仓 {MAX_POS} 只；每槽≈权益/{MAX_POS}；同日信号按池序（夏普）优先",
        f"标的池: {len(meta)} 只（watch_config 拟合池，个股自有阈值）",
        f"初始资金: {INITIAL_CASH:,.0f}",
        f"区间: {pm['start']} → {pm['end']}（约 {pm['years']} 年）",
        "",
        "=== 组合绩效 ===",
        f"总收益率: {pm['total_return_pct']:+.2f}%",
        f"年化收益: {pm['annualized_return_pct']:+.2f}%",
        f"最大回撤: {pm['max_drawdown_pct']:.2f}% @ {pm['max_drawdown_date']}",
        f"夏普: {pm['sharpe']:.3f}  波动: {pm['volatility_pct']:.2f}%",
        f"期末权益: {pm['end_equity']:,.2f}",
        "",
        "=== 对比：池内等权买入持有 ===",
        f"总收益率: {bm['total_return_pct']:+.2f}%",
        f"年化收益: {bm['annualized_return_pct']:+.2f}%",
        f"最大回撤: {bm['max_drawdown_pct']:.2f}%",
        f"超额（策略-持有）: {excess:+.2f}%",
        "",
        f"成交: 买 {n_buys} / 卖 {n_sells}  日均持仓数: {avg_hold:.2f}",
        "",
        "=== 分年 ===",
        yearly.to_string(index=False),
        "",
        "=== 最近持仓（15 日）===",
        recent_hold[["date", "n_hold", "names", "equity", "drawdown_pct", "events"]].to_string(
            index=False
        ),
        "",
        "=== 最近进出事件（最多 30 条有事件日）===",
        recent_events[["date", "n_hold", "detail", "events"]].to_string(index=False)
        if not recent_events.empty
        else "(无)",
        "",
        f"明细 CSV: {OUT_DIR}",
    ]
    text = "\n".join(lines) + "\n"
    (OUT_DIR / "summary.txt").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
