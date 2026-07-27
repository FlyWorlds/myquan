"""510300 沪深300ETF — 日线动量策略（历史参数优化版）.

规则（相对昨收，日线收盘成交）：
  - 信号：当日涨幅 >= 1.3%
  - 今天尾盘（收盘价）满仓买入
  - 持股 3 个交易日，第 3 个交易日尾盘卖出
  - 满仓

  参数说明：涨跌幅阈值与持仓天数基于历史回测扫描选取（不构成未来收益保证）。

数据 / 复权（akquant）：
  - 复权在**数据拉取层**控制，run_backtest() 本身无 adjust 参数
  - 股票可用 akquant.utils.fetch_akshare_symbol(..., adjust="qfq")
  - ETF 参考官方示例 examples/59_akshare_etf_rotation.py：
    ak.fund_etf_hist_em(..., adjust="qfq")
  - 本脚本 ETF 东财不可用时回退腾讯前复权

ETF 规则（akquant）：lot_size=100、T+1、免印花税。
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import cast

import akquant as aq
import akshare as ak
import pandas as pd
import requests
from akquant import CurrentClose, Strategy
from akquant.utils import prepare_dataframe

# ── 配置 ──────────────────────────────────────────────
SYMBOL = "510300"
SYMBOL_NAME = "沪深300ETF"
SINA_SYMBOL = "sh510300"

DATA_START = "20150401"       # 提前若干日，用于计算单日涨跌幅
BACKTEST_START = dt.date(2015, 4, 29)
DATA_END = dt.date.today().strftime("%Y%m%d")

ADJUST = "qfq"                # 前复权：akquant 推荐回测默认值（见 utils.fetch_akshare_symbol）

INITIAL_CASH = 100_000.0
LOT_SIZE = 100
GAIN_THRESHOLD = 0.013        # 单日涨幅 >= 1.3%（历史优化目标年化 ~10%）
POSITION_RATIO = 0.98         # 满仓（留 2% 缓冲应付手续费）
HOLD_DAYS = 3                 # 买入后持股 3 个交易日，第 3 日收盘卖
COMMISSION_RATE = 0.00006     # 佣金万 0.6
MIN_COMMISSION = 3.0

FILL_MODE = CurrentClose()

CACHE_PATH = Path(__file__).with_name(f"{SYMBOL}_daily_{ADJUST}.parquet")
REPORT_PATH = Path(__file__).with_name("hs300etf_report.html")
DAILY_CLOSE_CSV = Path(__file__).with_name(f"{SYMBOL}_daily_close_hs300.csv")


def round_lot(qty: float) -> int:
    return max(0, int(qty // LOT_SIZE) * LOT_SIZE)


def _to_ts(date_str: str, hhmm: str = "15:00:00") -> str:
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {hhmm}"


def _date_fmt(date_str: str) -> str:
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"


def _standardize_ohlcv(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """统一为 akquant 回测列结构（与官方 ETF 示例一致）."""
    rename_map = {
        "日期": "date", "day": "date",
        "开盘": "open", "最高": "high", "最低": "low",
        "收盘": "close", "成交量": "volume",
    }
    out = df.rename(columns=rename_map).copy()
    required = ["date", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise ValueError(f"缺少列 {missing}，实际: {out.columns.tolist()}")
    out = out[required].copy()
    out["date"] = pd.to_datetime(out["date"])
    for col in required[1:]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    out["symbol"] = symbol
    return cast(pd.DataFrame, out)


def _fetch_etf_hist_em(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str = ADJUST,
) -> pd.DataFrame:
    """akquant 官方 ETF 示例同款：fund_etf_hist_em + adjust."""
    raw = ak.fund_etf_hist_em(
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust=adjust,
    )
    if raw.empty:
        raise ValueError(f"东财 ETF 日线为空: {symbol}")
    return _standardize_ohlcv(raw, symbol)


def _fetch_tencent_daily(
    sina_symbol: str,
    start_date: str,
    end_date: str,
    adjust: str = ADJUST,
) -> pd.DataFrame:
    """腾讯财经日线（前复权 qfqday，与主流行情软件一致）.

    腾讯接口单次最多约 640 根 K 线，按年分段拉取后合并。
    """
    suffix_map = {"qfq": "qfq", "hfq": "hfq", "": ""}
    key_map = {"qfq": "qfqday", "hfq": "hfqday", "": "day"}
    suffix = suffix_map.get(adjust, "qfq")
    data_key = key_map[suffix]

    start_ts = pd.Timestamp(_date_fmt(start_date))
    end_ts = pd.Timestamp(_date_fmt(end_date))
    records: list[dict[str, str]] = []

    for year in range(start_ts.year, end_ts.year + 1):
        chunk_start = max(start_ts, pd.Timestamp(year, 1, 1))
        chunk_end = min(end_ts, pd.Timestamp(year, 12, 31))
        if chunk_start > chunk_end:
            continue
        s = chunk_start.strftime("%Y-%m-%d")
        e = chunk_end.strftime("%Y-%m-%d")
        param = f"{sina_symbol},day,{s},{e},640,{suffix}"
        resp = requests.get(
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
            params={"param": param},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json()["data"][sina_symbol][data_key]
        for row in rows:
            records.append(
                {
                    "date": row[0],
                    "open": row[1],
                    "close": row[2],
                    "high": row[3],
                    "low": row[4],
                    "volume": row[5],
                }
            )

    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["symbol"] = SYMBOL
    return _standardize_ohlcv(df, SYMBOL)


def fetch_etf_daily(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    adjust: str = ADJUST,
    use_cache: bool = True,
    refresh: bool = False,
) -> pd.DataFrame:
    """拉取 ETF 前复权日线.

    优先级（均在数据层指定 adjust，与 akquant 文档一致）：
      1. ak.fund_etf_hist_em(..., adjust=adjust)  — 官方 ETF 示例
      2. 腾讯财经 qfqday                           — 东财网络失败时回退
    """
    fetch_start = start_date or "19900101"
    fetch_end = end_date or DATA_END
    req_start = pd.Timestamp(_to_ts(fetch_start, "00:00:00"))

    df: pd.DataFrame | None = None
    if use_cache and not refresh and CACHE_PATH.exists():
        cached = pd.read_parquet(CACHE_PATH)
        cached["date"] = pd.to_datetime(cached["date"])
        if cached["date"].min() <= req_start:
            print(f"使用本地缓存: {CACHE_PATH.name}（{len(cached)} 天，adjust={adjust}）")
            df = cached
        else:
            print(
                f"缓存起始于 {cached['date'].min().date()}，不覆盖 {fetch_start}，重新拉取 …"
            )

    if df is None:
        source = ""
        errors: list[str] = []

        # ① akquant 推荐：ETF 用 fund_etf_hist_em(adjust="qfq")
        try:
            df = _fetch_etf_hist_em(symbol, fetch_start, fetch_end, adjust=adjust)
            source = f"东财 ETF 日线 adjust={adjust}"
        except Exception as exc:
            errors.append(f"东财: {exc}")

        # ② 回退：腾讯前复权（与行情软件一致）
        if (df is None or df.empty) and adjust == "qfq":
            try:
                df = _fetch_tencent_daily(SINA_SYMBOL, fetch_start, fetch_end, adjust="qfq")
                source = "腾讯财经 前复权（东财不可用）"
            except Exception as exc:
                errors.append(f"腾讯: {exc}")

        if df is None or df.empty:
            msg = "\n".join(f"    · {e}" for e in errors)
            raise RuntimeError(f"无法获取 ETF 前复权日线（adjust={adjust}）:\n{msg}")

        if use_cache:
            df.to_parquet(CACHE_PATH, index=False)
            print(f"已缓存: {CACHE_PATH.name}（{len(df)} 天，来源: {source}）")

    if start_date:
        start = pd.Timestamp(_to_ts(start_date, "00:00:00"))
        df = df[df["date"] >= start]
    if end_date:
        end = pd.Timestamp(_to_ts(end_date, "23:59:59"))
        df = df[df["date"] <= end]
    return cast(pd.DataFrame, df.reset_index(drop=True))


def daily_to_akquant(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """日线 → akquant 格式（每根 K 线时间戳为当日 15:00 收盘）."""
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize() + pd.Timedelta(hours=15)
    out["symbol"] = symbol
    required = ["date", "open", "high", "low", "close", "volume", "symbol"]
    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    return cast(pd.DataFrame, out[required])


def print_buy_hold_pnl(
    daily_df: pd.DataFrame,
    entry_date: dt.date,
    end_date: dt.date,
    initial_cash: float = INITIAL_CASH,
) -> dict[str, float | int | dt.date]:
    """无策略：首日开盘买入并持有至最新收盘."""
    daily = daily_df.copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    daily = daily.sort_values("date")

    entry_row = daily[daily["date"] >= entry_date].head(1)
    if entry_row.empty:
        raise ValueError(f"日线数据中没有 {entry_date} 及之后的交易日")
    exit_row = daily[daily["date"] <= end_date].tail(1)
    if exit_row.empty:
        raise ValueError(f"日线数据中没有 {end_date} 及之前的交易日")

    entry = entry_row.iloc[0]
    exit_ = exit_row.iloc[0]
    entry_price = float(entry["open"])
    exit_price = float(exit_["close"])
    qty = round_lot(initial_cash * 0.98 / entry_price)
    cost = entry_price * qty
    value = exit_price * qty
    pnl = value - cost
    pct = pnl / cost * 100 if cost else 0.0

    print("\n=== 无策略 · 买入持有 ===")
    print(f"  买入日:   {entry['date']}  (开盘价)")
    print(f"  买入价:   {entry_price:.3f} 元")
    print(f"  持仓:     {qty} 股")
    print(f"  买入成本: {cost:,.2f} 元")
    print(f"  现价日:   {exit_['date']}  收盘")
    print(f"  现价:     {exit_price:.3f} 元")
    print(f"  市值:     {value:,.2f} 元")
    print(f"  盈亏:     {pnl:+,.2f} 元 ({pct:+.2f}%)")
    return {
        "entry_date": entry["date"],
        "exit_date": exit_["date"],
        "entry_price": entry_price,
        "exit_price": exit_price,
        "qty": qty,
        "pnl": pnl,
        "pct": pct,
    }


class OptimizedRallyStrategy(Strategy):
    """单日涨 >=1.3% → 当天收盘满仓买，持股 3 日后卖."""

    def __init__(self, backtest_start: dt.date) -> None:
        super().__init__()
        self.backtest_start = backtest_start
        self.prev_close: float | None = None
        self.holding = False
        self.bars_until_sell = 0

    def _local_date(self, bar) -> dt.date:
        return self.to_local_time(bar.timestamp).date()

    def _daily_ret(self, close: float) -> float | None:
        if self.prev_close is None or self.prev_close <= 0:
            return None
        return (close - self.prev_close) / self.prev_close

    def on_bar(self, bar) -> None:
        bar_date = self._local_date(bar)
        ret = self._daily_ret(bar.close)

        if self.holding and self.bars_until_sell > 0:
            self.bars_until_sell -= 1
            if self.bars_until_sell == 0:
                pos = int(self.get_position(bar.symbol))
                if pos > 0:
                    self.close_position(symbol=bar.symbol)
                    print(
                        f"[{bar_date}] 持股{HOLD_DAYS}日收盘卖出 {pos} 股 @ {bar.close:.3f}"
                    )
                self.holding = False

        if (
            bar_date >= self.backtest_start
            and ret is not None
            and ret >= GAIN_THRESHOLD
            and not self.holding
        ):
            cash = self.cash
            qty = round_lot(cash * POSITION_RATIO / bar.close)
            if qty >= LOT_SIZE:
                self.buy(symbol=bar.symbol, quantity=qty, fill_mode=FILL_MODE)
                self.holding = True
                self.bars_until_sell = HOLD_DAYS
                print(
                    f"[{bar_date}] 信号：单日 +{ret * 100:.2f}% "
                    f"→ 当日收盘买入 {qty} 股 (满仓) @ {bar.close:.3f}"
                )

        self.prev_close = bar.close


def build_benchmark_returns(df: pd.DataFrame) -> pd.Series:
    daily = df.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.set_index("date").sort_index()
    return daily["close"].pct_change().fillna(0.0).rename("510300_BENCH")


def monthly_returns_from_equity(equity: pd.Series, from_date: dt.date) -> pd.DataFrame:
    """按自然月计算权益变动：当月末权益 / 上月末权益 - 1（非年化平均）."""
    eq = equity.sort_index().copy()
    eq.index = pd.to_datetime(eq.index)
    if eq.index.tz is not None:
        eq.index = eq.index.tz_convert("Asia/Shanghai")

    month_ends = eq.groupby(eq.index.to_period("M")).last()
    from_period = pd.Period(from_date, freq="M")

    rows: list[dict[str, float | int | str]] = []
    prev_end: float | None = None
    for period in sorted(month_ends.index):
        end_val = float(month_ends.loc[period])
        if period < from_period:
            prev_end = end_val
            continue
        if prev_end is None:
            chunk = eq[eq.index.to_period("M") == period]
            start_val = float(chunk.iloc[0])
        else:
            start_val = prev_end
        ret_pct = (end_val / start_val - 1) * 100 if start_val else 0.0
        rows.append(
            {
                "period": str(period),
                "year": period.year,
                "month": period.month,
                "return_pct": ret_pct,
                "pnl": end_val - start_val,
                "end_equity": end_val,
            }
        )
        prev_end = end_val
    return pd.DataFrame(rows)


def monthly_returns_buy_hold(
    daily_df: pd.DataFrame,
    entry_date: dt.date,
    end_date: dt.date,
    initial_cash: float = INITIAL_CASH,
) -> pd.DataFrame:
    """买入持有：各自然月按月末市值相对上月末（首月为买入成本）."""
    daily = daily_df.copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    daily = daily.sort_values("date")
    entry_row = daily[daily["date"] >= entry_date].head(1)
    if entry_row.empty:
        return pd.DataFrame()

    entry_price = float(entry_row.iloc[0]["open"])
    qty = round_lot(initial_cash * 0.98 / entry_price)
    entry_cost = entry_price * qty

    sub = daily[(daily["date"] >= entry_date) & (daily["date"] <= end_date)].copy()
    sub["value"] = qty * sub["close"].astype(float)
    sub["period"] = pd.to_datetime(sub["date"]).dt.to_period("M")
    month_ends = sub.groupby("period").last()

    from_period = pd.Period(entry_date, freq="M")
    rows: list[dict[str, float | str]] = []
    prev_end: float | None = None
    for period in sorted(month_ends.index):
        end_val = float(month_ends.loc[period]["value"])
        if period < from_period:
            prev_end = end_val
            continue
        start_val = entry_cost if prev_end is None else prev_end
        ret_pct = (end_val / start_val - 1) * 100 if start_val else 0.0
        rows.append({"period": str(period), "return_pct": ret_pct})
        prev_end = end_val
    return pd.DataFrame(rows)


def monthly_closed_trade_count(
    trades: pd.DataFrame, from_date: dt.date
) -> dict[str, int]:
    if trades.empty:
        return {}
    exit_periods = pd.to_datetime(trades["exit_time"]).dt.to_period("M")
    from_period = pd.Period(from_date, freq="M")
    counts = exit_periods[exit_periods >= from_period].value_counts()
    return {str(p): int(c) for p, c in counts.items()}


def print_monthly_returns(
    result: aq.BacktestResult,
    daily_df: pd.DataFrame,
    backtest_start: dt.date,
    end_date: dt.date,
) -> None:
    strat = monthly_returns_from_equity(result.equity_curve, backtest_start)
    bh = monthly_returns_buy_hold(daily_df, backtest_start, end_date)
    trade_counts = monthly_closed_trade_count(result.trades_df, backtest_start)
    bh_map = {str(r["period"]): float(r["return_pct"]) for _, r in bh.iterrows()}

    print("\n=== 分月度收益（日历月末口径，非年化平均）===")
    print(
        f"  {'月份':<8} {'策略收益':>10} {'买入持有':>10} "
        f"{'策略盈亏(元)':>14} {'平仓笔数':>8}"
    )
    print("  " + "-" * 58)

    last_year: int | None = None
    for _, row in strat.iterrows():
        year = int(row["year"])
        if last_year is not None and year != last_year:
            print()
        last_year = year
        period = str(row["period"])
        bh_pct = bh_map.get(period)
        bh_str = f"{bh_pct:+10.2f}%" if bh_pct is not None else "       n/a"
        n_trades = trade_counts.get(period, 0)
        print(
            f"  {period:<8} {row['return_pct']:+10.2f}% {bh_str} "
            f"{row['pnl']:+14,.0f} {n_trades:>8}"
        )
    print(
        "\n  说明：策略各月收益 = 当月末权益 / 上月末权益 - 1；"
        "买入持有首月起点为回测首日买入成本。"
    )


def yearly_returns_from_equity(equity: pd.Series, from_year: int) -> pd.DataFrame:
    """按自然年计算权益变动：当年末权益 / 上年末权益 - 1（非年化平均）."""
    eq = equity.sort_index().copy()
    eq.index = pd.to_datetime(eq.index)
    if eq.index.tz is not None:
        eq.index = eq.index.tz_convert("Asia/Shanghai")

    year_ends = eq.groupby(eq.index.year).last()
    rows: list[dict[str, float | int]] = []
    for year in year_ends.index:
        if year < from_year:
            continue
        end_val = float(year_ends.loc[year])
        prev_year = year - 1
        if prev_year in year_ends.index:
            start_val = float(year_ends.loc[prev_year])
        else:
            start_val = float(eq[eq.index.year == year].iloc[0])
        ret_pct = (end_val / start_val - 1) * 100 if start_val else 0.0
        rows.append(
            {
                "year": year,
                "start_equity": start_val,
                "end_equity": end_val,
                "return_pct": ret_pct,
                "pnl": end_val - start_val,
            }
        )
    return pd.DataFrame(rows)


def yearly_returns_buy_hold(
    daily_df: pd.DataFrame,
    entry_date: dt.date,
    end_date: dt.date,
    initial_cash: float = INITIAL_CASH,
) -> pd.DataFrame:
    """买入持有：各自然年按年末市值相对上年末（首年为买入成本）."""
    daily = daily_df.copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    daily = daily.sort_values("date")
    entry_row = daily[daily["date"] >= entry_date].head(1)
    if entry_row.empty:
        return pd.DataFrame()

    entry_price = float(entry_row.iloc[0]["open"])
    qty = round_lot(initial_cash * 0.98 / entry_price)
    entry_cost = entry_price * qty

    sub = daily[(daily["date"] >= entry_date) & (daily["date"] <= end_date)].copy()
    sub["value"] = qty * sub["close"].astype(float)
    year_ends = sub.groupby(sub["date"].apply(lambda d: d.year)).last()

    rows: list[dict[str, float | int]] = []
    for year in year_ends.index:
        end_val = float(year_ends.loc[year]["value"])
        prev_year = year - 1
        if prev_year in year_ends.index:
            start_val = float(year_ends.loc[prev_year]["value"])
        else:
            start_val = entry_cost
        ret_pct = (end_val / start_val - 1) * 100 if start_val else 0.0
        rows.append({"year": year, "return_pct": ret_pct, "end_value": end_val})
    return pd.DataFrame(rows)


def yearly_closed_trade_count(trades: pd.DataFrame, from_year: int) -> dict[int, int]:
    if trades.empty:
        return {}
    years = pd.to_datetime(trades["exit_time"]).dt.year
    counts = years[years >= from_year].value_counts()
    return {int(y): int(c) for y, c in counts.items()}


def print_yearly_returns(
    result: aq.BacktestResult,
    daily_df: pd.DataFrame,
    backtest_start: dt.date,
    end_date: dt.date,
) -> None:
    from_year = backtest_start.year
    strat = yearly_returns_from_equity(result.equity_curve, from_year)
    bh = yearly_returns_buy_hold(daily_df, backtest_start, end_date)
    trade_counts = yearly_closed_trade_count(result.trades_df, from_year)
    bh_map = {int(r["year"]): float(r["return_pct"]) for _, r in bh.iterrows()}

    print("\n=== 分年度收益（日历年末口径，非年化平均）===")
    print(
        f"  {'年份':<6} {'策略收益':>10} {'买入持有':>10} "
        f"{'策略盈亏(元)':>14} {'平仓笔数':>8}"
    )
    print("  " + "-" * 56)
    for _, row in strat.iterrows():
        year = int(row["year"])
        bh_pct = bh_map.get(year)
        bh_str = f"{bh_pct:+10.2f}%" if bh_pct is not None else "       n/a"
        n_trades = trade_counts.get(year, 0)
        print(
            f"  {year:<6} {row['return_pct']:+10.2f}% {bh_str} "
            f"{row['pnl']:+14,.0f} {n_trades:>8}"
        )
    print(
        "\n  说明：策略各年收益 = 当年末权益 / 上年末权益 - 1；"
        "买入持有首年起点为回测首日买入成本。"
    )


def print_trade_details(trades: pd.DataFrame) -> None:
    """逐笔打印：买入=信号日收盘价，卖出=次日收盘价."""
    if trades.empty:
        print("\n（无完整买卖回合，可能区间内未触发信号）")
        return

    print(f"\n=== 交易明细（{len(trades)} 笔）===")
    print("  规则：单日涨>=1.3% 当日收盘买；卖出价 = 买入后第 3 个交易日收盘价\n")

    total_net = 0.0
    wins = 0
    for i, row in trades.iterrows():
        n = trades.index.get_loc(i) + 1
        buy_date = pd.Timestamp(row["entry_time"]).strftime("%Y-%m-%d")
        sell_date = pd.Timestamp(row["exit_time"]).strftime("%Y-%m-%d")
        qty = int(row["quantity"])
        entry = float(row["entry_price"])
        exit_ = float(row["exit_price"])
        net = float(row["net_pnl"])
        ret = float(row["return_pct"])
        total_net += net
        if net > 0:
            wins += 1

        print(f"  第 {n:2d} 笔")
        print(f"    买入日:     {buy_date}  当日收盘 {entry:.3f} 元")
        print(f"    卖出日:     {sell_date}  持股3日收盘 {exit_:.3f} 元")
        print(f"    数量: {qty:,} 股  |  净盈亏: {net:+,.2f} 元  |  收益率: {ret:+.2f}%")
        print()

    losses = len(trades) - wins
    print(f"  合计净盈亏: {total_net:+,.2f} 元")
    print(f"  盈利 {wins} 笔 / 亏损 {losses} 笔")


def print_summary(result: aq.BacktestResult) -> None:
    metrics = result.metrics_df["value"]
    print("\n=== 关键指标 ===")
    for key in (
        "total_return_pct", "annualized_return", "max_drawdown_pct",
        "sharpe_ratio", "win_rate", "closed_trade_count", "total_commission",
    ):
        if key in metrics.index:
            print(f"  {key}: {metrics[key]}")
    print_trade_details(result.trades_df)


def run_backtest(refresh: bool = False) -> aq.BacktestResult:
    print(f"拉取 {SYMBOL_NAME}({SYMBOL}) 日线 adjust={ADJUST} …")
    print(f"  （akquant：复权在 fetch 层控制，run_backtest 无 adjust 参数）")
    print(f"回测区间: {BACKTEST_START} ~ {DATA_END}")

    daily_raw = fetch_etf_daily(
        SYMBOL,
        start_date=DATA_START, end_date=DATA_END,
        adjust=ADJUST, refresh=refresh,
    )
    end_date = pd.Timestamp(_to_ts(DATA_END, "00:00:00")).date()
    print_buy_hold_pnl(daily_raw, BACKTEST_START, end_date)

    df = daily_to_akquant(daily_raw, SYMBOL)
    df = prepare_dataframe(df, date_col="date", tz="Asia/Shanghai")
    print(f"\n日线数据: {len(df)} 天（{ADJUST}）")
    print(f"  覆盖区间: {pd.to_datetime(df['date']).min().date()} ~ "
          f"{pd.to_datetime(df['date']).max().date()}")

    sample = daily_raw[daily_raw["date"] == pd.Timestamp("2024-10-10")]
    if not sample.empty:
        print(f"  校验 2024-10-10 收盘价: {float(sample.iloc[0]['close']):.3f}")

    daily_raw.to_csv(DAILY_CLOSE_CSV, index=False, encoding="utf-8-sig")
    print(f"已保存: {DAILY_CLOSE_CSV.name}")

    class _Strategy(OptimizedRallyStrategy):
        def __init__(self) -> None:
            super().__init__(BACKTEST_START)

    result = aq.run_backtest(
        data=df,
        strategy=_Strategy,
        initial_cash=INITIAL_CASH,
        symbols=SYMBOL,
        lot_size=LOT_SIZE,
        t_plus_one=True,
        timezone="Asia/Shanghai",
        start_time=pd.Timestamp(_to_ts(DATA_START, "15:00:00")).date().isoformat(),
        end_time=_to_ts(DATA_END, "15:00:00"),
        fill_policy=FILL_MODE,
        commission_rate=COMMISSION_RATE,
        stamp_tax_rate=0.0,
        min_commission=MIN_COMMISSION,
        show_progress=True,
    )

    print("\n=== Backtest Result ===")
    print(result)
    print_summary(result)
    print_yearly_returns(result, daily_raw, BACKTEST_START, end_date)
    print_monthly_returns(result, daily_raw, BACKTEST_START, end_date)

    result.viz.report(
        filename=str(REPORT_PATH),
        show=False,
        benchmark=build_benchmark_returns(df),
    )
    print(f"\n报告: {REPORT_PATH.name}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"{SYMBOL_NAME} 涨1.3%买持3日策略(目标年化10%)"
    )
    parser.add_argument("--refresh", action="store_true", help="重新拉取日线数据")
    args = parser.parse_args()
    run_backtest(refresh=args.refresh)


if __name__ == "__main__":
    main()
