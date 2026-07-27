"""510500 中证500ETF — 低价加仓 / 盈利递减策略（zz500ETF2）.

规则（全部以日线收盘价成交）：
  【加仓】收盘价 < 5 元时：
    - 5 元基准目标仓位 80%
    - 每低于 5 元 1%，目标仓位 +1%（例：4.5 元→90%，4 元→100%），直至满仓
  【减仓】浮盈 >= 50% 时：
    - 首次触发：目标仓位降至 50%（减仓 50%）
    - 之后每多 1% 浮盈，目标仓位再减 1%（例：60% 浮盈→40% 仓位，100% 浮盈→清仓）

ETF：lot_size=100、T+1、免印花税、前复权 qfq。
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
SYMBOL = "510500"
SYMBOL_NAME = "中证500ETF"
SINA_SYMBOL = "sh510500"

DATA_START = "20150401"
BACKTEST_START = dt.date(2015, 4, 29)
DATA_END = dt.date.today().strftime("%Y%m%d")

ADJUST = "qfq"
INITIAL_CASH = 100_000.0
LOT_SIZE = 100
CASH_BUFFER = 0.98

# 策略参数
PRICE_ANCHOR = 5.0            # 5 元基准
BASE_POSITION_PCT = 0.80        # 5 元时目标仓位 80%
PROFIT_REDUCE_START = 0.50      # 浮盈 50% 起减仓
PROFIT_REDUCE_BASE = 0.50       # 浮盈 50% 时目标仓位 50%

COMMISSION_RATE = 0.00006
MIN_COMMISSION = 3.0
FILL_MODE = CurrentClose()

CACHE_PATH = Path(__file__).with_name(f"{SYMBOL}_daily_{ADJUST}.parquet")
REPORT_PATH = Path(__file__).with_name("zz500etf2_report.html")


def round_lot(qty: float) -> int:
    return max(0, int(qty // LOT_SIZE) * LOT_SIZE)


def _to_ts(date_str: str, hhmm: str = "15:00:00") -> str:
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {hhmm}"


def _date_fmt(date_str: str) -> str:
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"


def _standardize_ohlcv(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
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
    symbol: str, start_date: str, end_date: str, adjust: str = ADJUST
) -> pd.DataFrame:
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
    sina_symbol: str, start_date: str, end_date: str, adjust: str = ADJUST
) -> pd.DataFrame:
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
        param = (
            f"{sina_symbol},day,"
            f"{chunk_start.strftime('%Y-%m-%d')},{chunk_end.strftime('%Y-%m-%d')},640,{suffix}"
        )
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

    if df is None:
        errors: list[str] = []
        try:
            df = _fetch_etf_hist_em(symbol, fetch_start, fetch_end, adjust=adjust)
            source = f"东财 ETF 日线 adjust={adjust}"
        except Exception as exc:
            errors.append(f"东财: {exc}")
            df = None

        if (df is None or df.empty) and adjust == "qfq":
            try:
                df = _fetch_tencent_daily(SINA_SYMBOL, fetch_start, fetch_end, adjust="qfq")
                source = "腾讯财经 前复权"
            except Exception as exc:
                errors.append(f"腾讯: {exc}")

        if df is None or df.empty:
            msg = "\n".join(f"    · {e}" for e in errors)
            raise RuntimeError(f"无法获取 ETF 日线:\n{msg}")

        if use_cache:
            df.to_parquet(CACHE_PATH, index=False)
            print(f"已缓存: {CACHE_PATH.name}（{len(df)} 天，来源: {source}）")

    if start_date:
        df = df[df["date"] >= pd.Timestamp(_to_ts(start_date, "00:00:00"))]
    if end_date:
        df = df[df["date"] <= pd.Timestamp(_to_ts(end_date, "23:59:59"))]
    return cast(pd.DataFrame, df.reset_index(drop=True))


def daily_to_akquant(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize() + pd.Timedelta(hours=15)
    out["symbol"] = symbol
    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    return cast(
        pd.DataFrame,
        out[["date", "open", "high", "low", "close", "volume", "symbol"]],
    )


def target_position_on_dip(close: float) -> float | None:
    """低于 5 元：80% + 跌幅%，上限 100%."""
    if close >= PRICE_ANCHOR:
        return None
    drop_pct = (PRICE_ANCHOR - close) / PRICE_ANCHOR
    return min(1.0, BASE_POSITION_PCT + drop_pct)


def target_position_on_profit(profit_pct: float) -> float | None:
    """浮盈 >= 50%：50% 仓位起，每多 1% 浮盈减 1% 仓位."""
    if profit_pct < PROFIT_REDUCE_START:
        return None
    extra = profit_pct - PROFIT_REDUCE_START
    return max(0.0, PROFIT_REDUCE_BASE - extra)


def resolve_target_percent(close: float, profit_pct: float | None) -> float | None:
    """盈利减仓优先于低价加仓."""
    if profit_pct is not None:
        profit_target = target_position_on_profit(profit_pct)
        if profit_target is not None:
            return profit_target
    return target_position_on_dip(close)


def print_buy_hold_pnl(
    daily_df: pd.DataFrame,
    entry_date: dt.date,
    end_date: dt.date,
    initial_cash: float = INITIAL_CASH,
) -> None:
    daily = daily_df.copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    daily = daily.sort_values("date")
    entry_row = daily[daily["date"] >= entry_date].head(1)
    exit_row = daily[daily["date"] <= end_date].tail(1)
    if entry_row.empty or exit_row.empty:
        return
    entry_price = float(entry_row.iloc[0]["open"])
    exit_price = float(exit_row.iloc[0]["close"])
    qty = round_lot(initial_cash * CASH_BUFFER / entry_price)
    cost = entry_price * qty
    value = exit_price * qty
    pnl = value - cost
    pct = pnl / cost * 100 if cost else 0.0
    print("\n=== 无策略 · 买入持有（对照）===")
    print(f"  买入日: {entry_row.iloc[0]['date']}  开盘 {entry_price:.3f}")
    print(f"  现价日: {exit_row.iloc[0]['date']}  收盘 {exit_price:.3f}")
    print(f"  盈亏: {pnl:+,.2f} 元 ({pct:+.2f}%)")


class LowPriceScaleStrategy(Strategy):
    """低于 5 元递增加仓；高浮盈递增减仓（日线收盘）."""

    def __init__(self, backtest_start: dt.date, quiet: bool = False) -> None:
        super().__init__()
        self.backtest_start = backtest_start
        self.quiet = quiet
        self.cost_amount = 0.0
        self.cost_shares = 0

    def _log(self, msg: str) -> None:
        if not self.quiet:
            print(msg)

    def _local_date(self, bar) -> dt.date:
        return self.to_local_time(bar.timestamp).date()

    def _avg_cost(self) -> float | None:
        if self.cost_shares <= 0:
            return None
        return self.cost_amount / self.cost_shares

    def _profit_pct(self, close: float) -> float | None:
        avg = self._avg_cost()
        if avg is None or avg <= 0:
            return None
        return (close - avg) / avg

    def on_bar(self, bar) -> None:
        bar_date = self._local_date(bar)
        if bar_date < self.backtest_start:
            return

        pos_before = float(self.get_position(bar.symbol))
        profit_pct = self._profit_pct(bar.close)
        target = resolve_target_percent(bar.close, profit_pct)

        if target is not None:
            target = min(target, CASH_BUFFER)
            profit_str = f"浮盈 {profit_pct * 100:.1f}%" if profit_pct is not None else ""
            dip_str = (
                f"低于5元 {(PRICE_ANCHOR - bar.close) / PRICE_ANCHOR * 100:.1f}%"
                if bar.close < PRICE_ANCHOR
                else ""
            )
            self.order_target_percent(
                symbol=bar.symbol,
                target_percent=target,
                fill_mode=FILL_MODE,
            )
            pos_after = float(self.get_position(bar.symbol))
            delta = pos_after - pos_before
            if abs(delta) >= LOT_SIZE:
                action = "加仓" if delta > 0 else "减仓"
                self._log(
                    f"[{bar_date}] {action} → 目标 {target * 100:.0f}%  "
                    f"{'买入' if delta > 0 else '卖出'} {int(abs(delta))} 股 @ {bar.close:.3f}  "
                    f"({profit_str or dip_str})"
                )

            if pos_after > pos_before:
                bought = pos_after - pos_before
                self.cost_amount += bought * bar.close
                self.cost_shares += bought
            elif pos_after < pos_before and self.cost_shares > 0:
                sold = pos_before - pos_after
                self.cost_amount *= max(0.0, 1.0 - sold / pos_before)
                self.cost_shares = pos_after


def build_benchmark_returns(df: pd.DataFrame) -> pd.Series:
    daily = df.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.set_index("date").sort_index()
    return daily["close"].pct_change().fillna(0.0).rename(f"{SYMBOL}_BENCH")


def print_summary(result: aq.BacktestResult) -> None:
    metrics = result.metrics_df["value"]
    print("\n=== 关键指标 ===")
    for key in (
        "total_return_pct",
        "annualized_return",
        "max_drawdown_pct",
        "sharpe_ratio",
        "win_rate",
        "closed_trade_count",
        "total_commission",
    ):
        if key in metrics.index:
            val = metrics[key]
            if key == "annualized_return":
                print(f"  {key}: {float(val) * 100:.2f}%")
            elif key == "max_drawdown_pct":
                print(f"  {key}: {float(val):.2f}%")
            else:
                print(f"  {key}: {val}")


def run_backtest(refresh: bool = False) -> aq.BacktestResult:
    print(f"拉取 {SYMBOL_NAME}({SYMBOL}) 日线 adjust={ADJUST} …")
    print(f"回测区间: {BACKTEST_START} ~ {DATA_END}")
    print(
        f"\n策略规则（日线收盘）:\n"
        f"  加仓: 价<{PRICE_ANCHOR}元 → 目标仓位 {BASE_POSITION_PCT * 100:.0f}% "
        f"+ 每跌1%加1%，至满仓\n"
        f"  减仓: 浮盈>={PROFIT_REDUCE_START * 100:.0f}% → 目标仓位 {PROFIT_REDUCE_BASE * 100:.0f}%，"
        f"之后每多1%浮盈减1%仓位"
    )

    daily_raw = fetch_etf_daily(
        SYMBOL, start_date=DATA_START, end_date=DATA_END, adjust=ADJUST, refresh=refresh
    )
    end_date = pd.Timestamp(_to_ts(DATA_END, "00:00:00")).date()
    print_buy_hold_pnl(daily_raw, BACKTEST_START, end_date)

    df = daily_to_akquant(daily_raw, SYMBOL)
    df = prepare_dataframe(df, date_col="date", tz="Asia/Shanghai")
    print(
        f"\n日线: {len(df)} 天  "
        f"{pd.to_datetime(df['date']).min().date()} ~ "
        f"{pd.to_datetime(df['date']).max().date()}"
    )

    class _Strategy(LowPriceScaleStrategy):
        def __init__(self) -> None:
            super().__init__(BACKTEST_START, quiet=False)

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

    result.viz.report(
        filename=str(REPORT_PATH),
        show=False,
        benchmark=build_benchmark_returns(df),
    )
    print(f"\n报告: {REPORT_PATH.name}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=f"{SYMBOL_NAME} 低价加仓/盈利减仓策略")
    parser.add_argument("--refresh", action="store_true", help="重新拉取日线数据")
    args = parser.parse_args()
    run_backtest(refresh=args.refresh)


if __name__ == "__main__":
    main()
"""510500 中证500ETF — 低价加仓 / 盈利递减策略（zz500ETF2）.

规则（全部以日线收盘价成交）：
  【加仓】收盘价 < 5 元时：
    - 5 元基准目标仓位 80%
    - 每低于 5 元 1%，目标仓位 +1%（例：4.5 元→90%，4 元→100%），直至满仓
  【减仓】浮盈 >= 50% 时：
    - 首次触发：目标仓位降至 50%（减仓 50%）
    - 之后每多 1% 浮盈，目标仓位再减 1%（例：60% 浮盈→40% 仓位，100% 浮盈→清仓）

ETF：lot_size=100、T+1、免印花税、前复权 qfq。
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
SYMBOL = "510500"
SYMBOL_NAME = "中证500ETF"
SINA_SYMBOL = "sh510500"

DATA_START = "20150401"
BACKTEST_START = dt.date(2015, 4, 29)
DATA_END = dt.date.today().strftime("%Y%m%d")

ADJUST = "qfq"
INITIAL_CASH = 100_000.0
LOT_SIZE = 100
CASH_BUFFER = 0.98

# 策略参数
PRICE_ANCHOR = 5.0            # 5 元基准
BASE_POSITION_PCT = 0.80        # 5 元时目标仓位 80%
PROFIT_REDUCE_START = 0.50      # 浮盈 50% 起减仓
PROFIT_REDUCE_BASE = 0.50       # 浮盈 50% 时目标仓位 50%

COMMISSION_RATE = 0.00006
MIN_COMMISSION = 3.0
FILL_MODE = CurrentClose()

CACHE_PATH = Path(__file__).with_name(f"{SYMBOL}_daily_{ADJUST}.parquet")
REPORT_PATH = Path(__file__).with_name("zz500etf2_report.html")


def round_lot(qty: float) -> int:
    return max(0, int(qty // LOT_SIZE) * LOT_SIZE)


def _to_ts(date_str: str, hhmm: str = "15:00:00") -> str:
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {hhmm}"


def _date_fmt(date_str: str) -> str:
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"


def _standardize_ohlcv(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
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
    symbol: str, start_date: str, end_date: str, adjust: str = ADJUST
) -> pd.DataFrame:
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
    sina_symbol: str, start_date: str, end_date: str, adjust: str = ADJUST
) -> pd.DataFrame:
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
        param = (
            f"{sina_symbol},day,"
            f"{chunk_start.strftime('%Y-%m-%d')},{chunk_end.strftime('%Y-%m-%d')},640,{suffix}"
        )
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

    if df is None:
        errors: list[str] = []
        try:
            df = _fetch_etf_hist_em(symbol, fetch_start, fetch_end, adjust=adjust)
            source = f"东财 ETF 日线 adjust={adjust}"
        except Exception as exc:
            errors.append(f"东财: {exc}")
            df = None

        if (df is None or df.empty) and adjust == "qfq":
            try:
                df = _fetch_tencent_daily(SINA_SYMBOL, fetch_start, fetch_end, adjust="qfq")
                source = "腾讯财经 前复权"
            except Exception as exc:
                errors.append(f"腾讯: {exc}")

        if df is None or df.empty:
            msg = "\n".join(f"    · {e}" for e in errors)
            raise RuntimeError(f"无法获取 ETF 日线:\n{msg}")

        if use_cache:
            df.to_parquet(CACHE_PATH, index=False)
            print(f"已缓存: {CACHE_PATH.name}（{len(df)} 天，来源: {source}）")

    if start_date:
        df = df[df["date"] >= pd.Timestamp(_to_ts(start_date, "00:00:00"))]
    if end_date:
        df = df[df["date"] <= pd.Timestamp(_to_ts(end_date, "23:59:59"))]
    return cast(pd.DataFrame, df.reset_index(drop=True))


def daily_to_akquant(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize() + pd.Timedelta(hours=15)
    out["symbol"] = symbol
    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    return cast(
        pd.DataFrame,
        out[["date", "open", "high", "low", "close", "volume", "symbol"]],
    )


def target_position_on_dip(close: float) -> float | None:
    """低于 5 元：80% + 跌幅%，上限 100%."""
    if close >= PRICE_ANCHOR:
        return None
    drop_pct = (PRICE_ANCHOR - close) / PRICE_ANCHOR
    return min(1.0, BASE_POSITION_PCT + drop_pct)


def target_position_on_profit(profit_pct: float) -> float | None:
    """浮盈 >= 50%：50% 仓位起，每多 1% 浮盈减 1% 仓位."""
    if profit_pct < PROFIT_REDUCE_START:
        return None
    extra = profit_pct - PROFIT_REDUCE_START
    return max(0.0, PROFIT_REDUCE_BASE - extra)


def resolve_target_percent(close: float, profit_pct: float | None) -> float | None:
    """盈利减仓优先于低价加仓."""
    if profit_pct is not None:
        profit_target = target_position_on_profit(profit_pct)
        if profit_target is not None:
            return profit_target
    return target_position_on_dip(close)


def print_buy_hold_pnl(
    daily_df: pd.DataFrame,
    entry_date: dt.date,
    end_date: dt.date,
    initial_cash: float = INITIAL_CASH,
) -> None:
    daily = daily_df.copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    daily = daily.sort_values("date")
    entry_row = daily[daily["date"] >= entry_date].head(1)
    exit_row = daily[daily["date"] <= end_date].tail(1)
    if entry_row.empty or exit_row.empty:
        return
    entry_price = float(entry_row.iloc[0]["open"])
    exit_price = float(exit_row.iloc[0]["close"])
    qty = round_lot(initial_cash * CASH_BUFFER / entry_price)
    cost = entry_price * qty
    value = exit_price * qty
    pnl = value - cost
    pct = pnl / cost * 100 if cost else 0.0
    print("\n=== 无策略 · 买入持有（对照）===")
    print(f"  买入日: {entry_row.iloc[0]['date']}  开盘 {entry_price:.3f}")
    print(f"  现价日: {exit_row.iloc[0]['date']}  收盘 {exit_price:.3f}")
    print(f"  盈亏: {pnl:+,.2f} 元 ({pct:+.2f}%)")


class LowPriceScaleStrategy(Strategy):
    """低于 5 元递增加仓；高浮盈递增减仓（日线收盘）."""

    def __init__(self, backtest_start: dt.date, quiet: bool = False) -> None:
        super().__init__()
        self.backtest_start = backtest_start
        self.quiet = quiet
        self.cost_amount = 0.0
        self.cost_shares = 0

    def _log(self, msg: str) -> None:
        if not self.quiet:
            print(msg)

    def _local_date(self, bar) -> dt.date:
        return self.to_local_time(bar.timestamp).date()

    def _avg_cost(self) -> float | None:
        if self.cost_shares <= 0:
            return None
        return self.cost_amount / self.cost_shares

    def _profit_pct(self, close: float) -> float | None:
        avg = self._avg_cost()
        if avg is None or avg <= 0:
            return None
        return (close - avg) / avg

    def _sync_cost_after_trade(self, bar) -> None:
        pos = float(self.get_position(bar.symbol))
        if pos <= 0:
            self.cost_amount = 0.0
            self.cost_shares = 0
        elif self.cost_shares <= 0:
            self.cost_shares = pos
            self.cost_amount = pos * bar.close

    def on_bar(self, bar) -> None:
        bar_date = self._local_date(bar)
        if bar_date < self.backtest_start:
            return

        pos_before = float(self.get_position(bar.symbol))
        profit_pct = self._profit_pct(bar.close)
        target = resolve_target_percent(bar.close, profit_pct)

        if target is not None:
            target = min(target, CASH_BUFFER)
            self.order_target_percent(
                symbol=bar.symbol,
                target_percent=target,
                fill_mode=FILL_MODE,
            )

        pos_after = float(self.get_position(bar.symbol))
        if pos_after > pos_before:
            bought = pos_after - pos_before
            self.cost_amount += bought * bar.close
            self.cost_shares += bought
            drop = (PRICE_ANCHOR - bar.close) / PRICE_ANCHOR * 100 if bar.close < PRICE_ANCHOR else 0
            self._log(
                f"[{bar_date}] 加仓 → 目标 {target * 100:.0f}%  "
                f"买入 {int(bought)} 股 @ {bar.close:.3f}  "
                f"(低于5元 {drop:.1f}%)"
            )
        elif pos_after < pos_before:
            sold = pos_before - pos_after
            if self.cost_shares > 0:
                self.cost_amount *= max(0.0, 1.0 - sold / pos_before)
                self.cost_shares = pos_after
            pstr = f"浮盈 {profit_pct * 100:.1f}%" if profit_pct is not None else ""
            self._log(
                f"[{bar_date}] 减仓 → 目标 {target * 100:.0f}%  "
                f"卖出 {int(sold)} 股 @ {bar.close:.3f}  ({pstr})"
            )


def build_benchmark_returns(df: pd.DataFrame) -> pd.Series:
    daily = df.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.set_index("date").sort_index()
    return daily["close"].pct_change().fillna(0.0).rename(f"{SYMBOL}_BENCH")


def print_summary(result: aq.BacktestResult) -> None:
    metrics = result.metrics_df["value"]
    print("\n=== 关键指标 ===")
    for key in (
        "total_return_pct",
        "annualized_return",
        "max_drawdown_pct",
        "sharpe_ratio",
        "win_rate",
        "closed_trade_count",
        "total_commission",
    ):
        if key in metrics.index:
            val = metrics[key]
            if key == "annualized_return":
                print(f"  {key}: {float(val) * 100:.2f}%")
            elif key == "max_drawdown_pct":
                print(f"  {key}: {float(val):.2f}%")
            else:
                print(f"  {key}: {val}")


def run_backtest(refresh: bool = False) -> aq.BacktestResult:
    print(f"拉取 {SYMBOL_NAME}({SYMBOL}) 日线 adjust={ADJUST} …")
    print(f"回测区间: {BACKTEST_START} ~ {DATA_END}")
    print(
        f"\n策略规则（日线收盘）:\n"
        f"  加仓: 价<{PRICE_ANCHOR}元 → 目标仓位 {BASE_POSITION_PCT * 100:.0f}% "
        f"+ 每跌1%加1%，至满仓\n"
        f"  减仓: 浮盈>={PROFIT_REDUCE_START * 100:.0f}% → 目标仓位 {PROFIT_REDUCE_BASE * 100:.0f}%，"
        f"之后每多1%浮盈减1%仓位"
    )

    daily_raw = fetch_etf_daily(
        SYMBOL, start_date=DATA_START, end_date=DATA_END, adjust=ADJUST, refresh=refresh
    )
    end_date = pd.Timestamp(_to_ts(DATA_END, "00:00:00")).date()
    print_buy_hold_pnl(daily_raw, BACKTEST_START, end_date)

    df = daily_to_akquant(daily_raw, SYMBOL)
    df = prepare_dataframe(df, date_col="date", tz="Asia/Shanghai")
    print(
        f"\n日线: {len(df)} 天  "
        f"{pd.to_datetime(df['date']).min().date()} ~ "
        f"{pd.to_datetime(df['date']).max().date()}"
    )

    class _Strategy(LowPriceScaleStrategy):
        def __init__(self) -> None:
            super().__init__(BACKTEST_START, quiet=False)

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

    result.viz.report(
        filename=str(REPORT_PATH),
        show=False,
        benchmark=build_benchmark_returns(df),
    )
    print(f"\n报告: {REPORT_PATH.name}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=f"{SYMBOL_NAME} 低价加仓/盈利减仓策略")
    parser.add_argument("--refresh", action="store_true", help="重新拉取日线数据")
    args = parser.parse_args()
    run_backtest(refresh=args.refresh)


if __name__ == "__main__":
    main()
"""510500 中证500ETF — 低价加仓 / 盈利递减策略（zz500ETF2）.

规则（全部以日线收盘价成交）：
  【加仓】收盘价 < 5 元时：
    - 5 元基准目标仓位 80%
    - 每低于 5 元 1%，目标仓位 +1%（例：4.5 元→90%，4 元→100%），直至满仓
  【减仓】浮盈 >= 50% 时：
    - 首次触发：目标仓位降至 50%（减仓 50%）
    - 之后每多 1% 浮盈，目标仓位再减 1%（例：60% 浮盈→40% 仓位，100% 浮盈→清仓）

ETF：lot_size=100、T+1、免印花税、前复权 qfq。
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
SYMBOL = "510500"
SYMBOL_NAME = "中证500ETF"
SINA_SYMBOL = "sh510500"

DATA_START = "20150401"
BACKTEST_START = dt.date(2015, 4, 29)
DATA_END = dt.date.today().strftime("%Y%m%d")

ADJUST = "qfq"
INITIAL_CASH = 100_000.0
LOT_SIZE = 100
CASH_BUFFER = 0.98

# 策略参数
PRICE_ANCHOR = 5.0            # 5 元基准
BASE_POSITION_PCT = 0.80        # 5 元时目标仓位 80%
PROFIT_REDUCE_START = 0.50      # 浮盈 50% 起减仓
PROFIT_REDUCE_BASE = 0.50       # 浮盈 50% 时目标仓位 50%

COMMISSION_RATE = 0.00006
MIN_COMMISSION = 3.0
FILL_MODE = CurrentClose()

CACHE_PATH = Path(__file__).with_name(f"{SYMBOL}_daily_{ADJUST}.parquet")
REPORT_PATH = Path(__file__).with_name("zz500etf2_report.html")


def round_lot(qty: float) -> int:
    return max(0, int(qty // LOT_SIZE) * LOT_SIZE)


def _to_ts(date_str: str, hhmm: str = "15:00:00") -> str:
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {hhmm}"


def _date_fmt(date_str: str) -> str:
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"


def _standardize_ohlcv(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
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
    symbol: str, start_date: str, end_date: str, adjust: str = ADJUST
) -> pd.DataFrame:
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
    sina_symbol: str, start_date: str, end_date: str, adjust: str = ADJUST
) -> pd.DataFrame:
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
        param = (
            f"{sina_symbol},day,"
            f"{chunk_start.strftime('%Y-%m-%d')},{chunk_end.strftime('%Y-%m-%d')},640,{suffix}"
        )
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

    if df is None:
        errors: list[str] = []
        try:
            df = _fetch_etf_hist_em(symbol, fetch_start, fetch_end, adjust=adjust)
            source = f"东财 ETF 日线 adjust={adjust}"
        except Exception as exc:
            errors.append(f"东财: {exc}")
            df = None

        if (df is None or df.empty) and adjust == "qfq":
            try:
                df = _fetch_tencent_daily(SINA_SYMBOL, fetch_start, fetch_end, adjust="qfq")
                source = "腾讯财经 前复权"
            except Exception as exc:
                errors.append(f"腾讯: {exc}")

        if df is None or df.empty:
            msg = "\n".join(f"    · {e}" for e in errors)
            raise RuntimeError(f"无法获取 ETF 日线:\n{msg}")

        if use_cache:
            df.to_parquet(CACHE_PATH, index=False)
            print(f"已缓存: {CACHE_PATH.name}（{len(df)} 天，来源: {source}）")

    if start_date:
        df = df[df["date"] >= pd.Timestamp(_to_ts(start_date, "00:00:00"))]
    if end_date:
        df = df[df["date"] <= pd.Timestamp(_to_ts(end_date, "23:59:59"))]
    return cast(pd.DataFrame, df.reset_index(drop=True))


def daily_to_akquant(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize() + pd.Timedelta(hours=15)
    out["symbol"] = symbol
    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    return cast(
        pd.DataFrame,
        out[["date", "open", "high", "low", "close", "volume", "symbol"]],
    )


def target_position_on_dip(close: float) -> float | None:
    """低于 5 元：80% + 跌幅%，上限 100%."""
    if close >= PRICE_ANCHOR:
        return None
    drop_pct = (PRICE_ANCHOR - close) / PRICE_ANCHOR
    return min(1.0, BASE_POSITION_PCT + drop_pct)


def target_position_on_profit(profit_pct: float) -> float | None:
    """浮盈 >= 50%：50% 仓位起，每多 1% 浮盈减 1% 仓位."""
    if profit_pct < PROFIT_REDUCE_START:
        return None
    extra = profit_pct - PROFIT_REDUCE_START
    return max(0.0, PROFIT_REDUCE_BASE - extra)


def resolve_target_percent(close: float, profit_pct: float | None) -> float | None:
    """盈利减仓优先于低价加仓."""
    if profit_pct is not None:
        profit_target = target_position_on_profit(profit_pct)
        if profit_target is not None:
            return profit_target
    return target_position_on_dip(close)


def print_buy_hold_pnl(
    daily_df: pd.DataFrame,
    entry_date: dt.date,
    end_date: dt.date,
    initial_cash: float = INITIAL_CASH,
) -> None:
    daily = daily_df.copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    daily = daily.sort_values("date")
    entry_row = daily[daily["date"] >= entry_date].head(1)
    exit_row = daily[daily["date"] <= end_date].tail(1)
    if entry_row.empty or exit_row.empty:
        return
    entry_price = float(entry_row.iloc[0]["open"])
    exit_price = float(exit_row.iloc[0]["close"])
    qty = round_lot(initial_cash * CASH_BUFFER / entry_price)
    cost = entry_price * qty
    value = exit_price * qty
    pnl = value - cost
    pct = pnl / cost * 100 if cost else 0.0
    print("\n=== 无策略 · 买入持有（对照）===")
    print(f"  买入日: {entry_row.iloc[0]['date']}  开盘 {entry_price:.3f}")
    print(f"  现价日: {exit_row.iloc[0]['date']}  收盘 {exit_price:.3f}")
    print(f"  盈亏: {pnl:+,.2f} 元 ({pct:+.2f}%)")


class LowPriceScaleStrategy(Strategy):
    """低于 5 元递增加仓；高浮盈递增减仓（日线收盘）."""

    def __init__(self, backtest_start: dt.date, quiet: bool = False) -> None:
        super().__init__()
        self.backtest_start = backtest_start
        self.quiet = quiet
        self.cost_amount = 0.0
        self.cost_shares = 0

    def _log(self, msg: str) -> None:
        if not self.quiet:
            print(msg)

    def _local_date(self, bar) -> dt.date:
        return self.to_local_time(bar.timestamp).date()

    def _avg_cost(self) -> float | None:
        if self.cost_shares <= 0:
            return None
        return self.cost_amount / self.cost_shares

    def _profit_pct(self, close: float) -> float | None:
        avg = self._avg_cost()
        if avg is None or avg <= 0:
            return None
        return (close - avg) / avg

    def _sync_cost_after_trade(self, bar) -> None:
        pos = float(self.get_position(bar.symbol))
        if pos <= 0:
            self.cost_amount = 0.0
            self.cost_shares = 0
        elif self.cost_shares <= 0:
            self.cost_shares = pos
            self.cost_amount = pos * bar.close

    def on_bar(self, bar) -> None:
        bar_date = self._local_date(bar)
        if bar_date < self.backtest_start:
            return

        pos_before = float(self.get_position(bar.symbol))
        profit_pct = self._profit_pct(bar.close)
        target = resolve_target_percent(bar.close, profit_pct)

        if target is not None:
            target = min(target, CASH_BUFFER)
            self.order_target_percent(
                symbol=bar.symbol,
                target_percent=target,
                fill_mode=FILL_MODE,
            )

        pos_after = float(self.get_position(bar.symbol))
        if pos_after > pos_before:
            bought = pos_after - pos_before
            self.cost_amount += bought * bar.close
            self.cost_shares += bought
            drop = (PRICE_ANCHOR - bar.close) / PRICE_ANCHOR * 100 if bar.close < PRICE_ANCHOR else 0
            self._log(
                f"[{bar_date}] 加仓 → 目标 {target * 100:.0f}%  "
                f"买入 {int(bought)} 股 @ {bar.close:.3f}  "
                f"(低于5元 {drop:.1f}%)"
            )
        elif pos_after < pos_before:
            sold = pos_before - pos_after
            if self.cost_shares > 0:
                self.cost_amount *= max(0.0, 1.0 - sold / pos_before)
                self.cost_shares = pos_after
            pstr = f"浮盈 {profit_pct * 100:.1f}%" if profit_pct is not None else ""
            self._log(
                f"[{bar_date}] 减仓 → 目标 {target * 100:.0f}%  "
                f"卖出 {int(sold)} 股 @ {bar.close:.3f}  ({pstr})"
            )


def build_benchmark_returns(df: pd.DataFrame) -> pd.Series:
    daily = df.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.set_index("date").sort_index()
    return daily["close"].pct_change().fillna(0.0).rename(f"{SYMBOL}_BENCH")


def print_summary(result: aq.BacktestResult) -> None:
    metrics = result.metrics_df["value"]
    print("\n=== 关键指标 ===")
    for key in (
        "total_return_pct",
        "annualized_return",
        "max_drawdown_pct",
        "sharpe_ratio",
        "win_rate",
        "closed_trade_count",
        "total_commission",
    ):
        if key in metrics.index:
            val = metrics[key]
            if key == "annualized_return":
                print(f"  {key}: {float(val) * 100:.2f}%")
            elif key == "max_drawdown_pct":
                print(f"  {key}: {float(val):.2f}%")
            else:
                print(f"  {key}: {val}")


def run_backtest(refresh: bool = False) -> aq.BacktestResult:
    print(f"拉取 {SYMBOL_NAME}({SYMBOL}) 日线 adjust={ADJUST} …")
    print(f"回测区间: {BACKTEST_START} ~ {DATA_END}")
    print(
        f"\n策略规则（日线收盘）:\n"
        f"  加仓: 价<{PRICE_ANCHOR}元 → 目标仓位 {BASE_POSITION_PCT * 100:.0f}% "
        f"+ 每跌1%加1%，至满仓\n"
        f"  减仓: 浮盈>={PROFIT_REDUCE_START * 100:.0f}% → 目标仓位 {PROFIT_REDUCE_BASE * 100:.0f}%，"
        f"之后每多1%浮盈减1%仓位"
    )

    daily_raw = fetch_etf_daily(
        SYMBOL, start_date=DATA_START, end_date=DATA_END, adjust=ADJUST, refresh=refresh
    )
    end_date = pd.Timestamp(_to_ts(DATA_END, "00:00:00")).date()
    print_buy_hold_pnl(daily_raw, BACKTEST_START, end_date)

    df = daily_to_akquant(daily_raw, SYMBOL)
    df = prepare_dataframe(df, date_col="date", tz="Asia/Shanghai")
    print(
        f"\n日线: {len(df)} 天  "
        f"{pd.to_datetime(df['date']).min().date()} ~ "
        f"{pd.to_datetime(df['date']).max().date()}"
    )

    class _Strategy(LowPriceScaleStrategy):
        def __init__(self) -> None:
            super().__init__(BACKTEST_START, quiet=False)

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

    result.viz.report(
        filename=str(REPORT_PATH),
        show=False,
        benchmark=build_benchmark_returns(df),
    )
    print(f"\n报告: {REPORT_PATH.name}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=f"{SYMBOL_NAME} 低价加仓/盈利减仓策略")
    parser.add_argument("--refresh", action="store_true", help="重新拉取日线数据")
    args = parser.parse_args()
    run_backtest(refresh=args.refresh)


if __name__ == "__main__":
    main()
