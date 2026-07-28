
"""
zz500ETF3.py

中证500ETF(510500) 动态牛熊策略

买入（盘中可触发，不依赖收盘是否阳线）：
  · 当天最高价相对开盘 ≥ ENTRY_PCT（默认 1.2%）→ 按开盘+阈值价买入
  · 前一日必须是：阴线，或涨幅 < 1% 的小阳线（避免连续两根阳线追买）

持仓 / 退出：
1. MA60 判断市场状态（牛/熊/震荡）
2. 熊市止损 1.2% / 震荡 1.5% / 牛市 2.0%
3. 牛市取消阴线立即卖出，改用 MA20 趋势退出
4. 牛市盈利 10% 后启动 5% 移动止盈
5. 非牛市：阴线收盘卖出（收盘后才可判定）

运行:
python zz500ETF3.py
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import akquant as aq
import akshare as ak
import pandas as pd

from akquant import Strategy, CurrentClose


SYMBOL = "510500"
SINA_SYMBOL = "sh510500"
SYMBOL_NAME = "中证500ETF"

START_DATE = "20240101"
END_DATE = dt.date.today().strftime("%Y%m%d")

INITIAL_CASH = 100000
TARGET_PCT = 0.95
LOT_SIZE = 100

ENTRY_PCT = 0.012
# 前一日小阳线：相对开盘涨幅上限（小于 1 个点）
PREV_SMALL_YANG_PCT = 0.01

STOP_BEAR = 0.012
STOP_SIDE = 0.015
STOP_BULL = 0.020

FILL_CLOSE = CurrentClose()
REPORT_PATH = Path(__file__).with_name("zz500ETF3_report.html")
# MA60 预热：多拉约 1 年日线再截到回测起点
WARMUP_START = "20221001"
# bar 无自定义列时，用日期查 MA（由 fetch_daily 填充）
MA_BY_DAY: dict[str, tuple[float, float]] = {}


def _fetch_tencent_daily(sina_symbol: str, start: str, end: str) -> pd.DataFrame:
    import requests

    start_ts = pd.Timestamp(f"{start[:4]}-{start[4:6]}-{start[6:8]}")
    end_ts = pd.Timestamp(f"{end[:4]}-{end[4:6]}-{end[6:8]}")
    records: list[dict] = []
    for year in range(start_ts.year, end_ts.year + 1):
        chunk_start = max(start_ts, pd.Timestamp(year, 1, 1))
        chunk_end = min(end_ts, pd.Timestamp(year, 12, 31))
        if chunk_start > chunk_end:
            continue
        param = (
            f"{sina_symbol},day,"
            f"{chunk_start.strftime('%Y-%m-%d')},"
            f"{chunk_end.strftime('%Y-%m-%d')},640,qfq"
        )
        resp = requests.get(
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
            params={"param": param},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json()["data"][sina_symbol]["qfqday"]
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
    return pd.DataFrame(records)


def _load_local_csv(start: str, end: str) -> pd.DataFrame:
    path = Path(__file__).with_name("510500_daily_close_zz500etf.csv")
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    start_ts = pd.Timestamp(f"{start[:4]}-{start[4:6]}-{start[6:8]}")
    end_ts = pd.Timestamp(f"{end[:4]}-{end[4:6]}-{end[6:8]}")
    return df[(df["date"] >= start_ts) & (df["date"] <= end_ts)].copy()


def fetch_daily(symbol, start, end):
    """前复权日线 + MA20/MA60；东财失败则腾讯/本地 CSV。先预热再截到 start。"""
    warm = WARMUP_START
    raw = None
    try:
        raw = ak.fund_etf_hist_em(
            symbol=SYMBOL,
            period="daily",
            start_date=warm,
            end_date=end,
            adjust="qfq",
        )
    except Exception as e:  # noqa: BLE001
        print(f"fund_etf_hist_em 失败: {e}")

    if raw is None or getattr(raw, "empty", True):
        try:
            print(f"回退腾讯日线: {SINA_SYMBOL}")
            raw = _fetch_tencent_daily(SINA_SYMBOL, warm, end)
        except Exception as e:  # noqa: BLE001
            print(f"腾讯日线失败: {e}")
            raw = None

    if raw is None or getattr(raw, "empty", True):
        print("回退本地 CSV: 510500_daily_close_zz500etf.csv")
        raw = _load_local_csv(warm, end)

    if raw is None or raw.empty:
        raise RuntimeError(f"未获取到日线: {SYMBOL} {warm}~{end}")

    df = raw.copy()
    df = df.rename(
        columns={
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
        }
    )
    df["date"] = pd.to_datetime(df["date"])
    for c in ["open", "close", "high", "low", "volume"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")

    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["symbol"] = SYMBOL

    start_ts = pd.Timestamp(f"{start[:4]}-{start[4:6]}-{start[6:8]}")
    df = df[df["date"] >= start_ts].copy()

    df["date"] = df["date"].dt.normalize() + pd.Timedelta(hours=15)
    if df["date"].dt.tz is None:
        df["date"] = df["date"].dt.tz_localize("Asia/Shanghai")

    print(f"日线数: {len(df)}，区间: {df['date'].iloc[0]} → {df['date'].iloc[-1]}")
    MA_BY_DAY.clear()
    for _, row in df.iterrows():
        day = pd.Timestamp(row["date"]).tz_convert("Asia/Shanghai").strftime("%Y-%m-%d")
        m20 = float(row["ma20"]) if pd.notna(row["ma20"]) else float("nan")
        m60 = float(row["ma60"]) if pd.notna(row["ma60"]) else float("nan")
        MA_BY_DAY[day] = (m20, m60)
    return df[
        [
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "symbol",
        ]
    ].reset_index(drop=True)



def entry_price(open_px):
    return round(open_px*(1+ENTRY_PCT),2)



def prev_day_allows_entry(prev_open: float, prev_close: float) -> bool:
    """前一日是否允许今日买入：阴线，或涨幅 < 1% 的小阳；禁止连续两根阳线追买。"""
    if prev_open <= 0:
        return False
    # 阴线（含收平按允许）
    if prev_close <= prev_open:
        return True
    # 小阳：相对开盘涨幅 < 1 个点
    return (prev_close / prev_open - 1.0) < PREV_SMALL_YANG_PCT


class BullBearETFStrategy(Strategy):

    def on_start(self):

        self.subscribe(SYMBOL)

        self.entry_price = None
        self.highest_price = None
        self.prev_open: float | None = None
        self.prev_close: float | None = None

        self.regime = "SIDE"

        self.log(
            f"中证500ETF动态牛熊 | 买入: high>=open×{1+ENTRY_PCT:.3f}；"
            f"前日须阴线或小阳(<{PREV_SMALL_YANG_PCT*100:.0f}%)"
        )


    def update_regime(self, close, ma60):

        if pd.isna(ma60):
            return "SIDE"

        if close > ma60*1.05:
            return "BULL"

        if close < ma60*0.95:
            return "BEAR"

        return "SIDE"



    def stop_pct(self):

        if self.regime=="BULL":
            return STOP_BULL

        if self.regime=="BEAR":
            return STOP_BEAR

        return STOP_SIDE



    def buy(self, price):

        self.order_target_percent(
            symbol=SYMBOL,
            target_percent=TARGET_PCT,
            price=price,
            fill_mode=FILL_CLOSE
        )

        self.entry_price = price
        self.highest_price = price



    def sell_all(self, price, reason):

        qty = self.get_available_position(SYMBOL)

        if qty>0:

            self.sell(
                SYMBOL,
                qty,
                price=price,
                fill_mode=FILL_CLOSE
            )

            self.log(
                f"{reason} @ {price}"
            )

        self.entry_price=None
        self.highest_price=None



    def on_bar(self, bar):

        if bar.symbol != SYMBOL:
            return


        o=float(bar.open)
        h=float(bar.high)
        l=float(bar.low)
        c=float(bar.close)

        day = self.to_local_time(bar.timestamp).strftime("%Y-%m-%d")
        ma20, ma60 = MA_BY_DAY.get(day, (float("nan"), float("nan")))

        try:
            self.regime = self.update_regime(
                c,
                ma60
            )


            pos=float(
                self.get_position(SYMBOL)
            )


            # 空仓买入：只认盘中冲高≥阈值；前日须阴线或小阳（不看当日收盘是否阳）
            if pos<=0 and self.prev_open is not None and self.prev_close is not None:

                buy_px=entry_price(o)

                if h>=buy_px and prev_day_allows_entry(self.prev_open, self.prev_close):

                    self.buy(
                        buy_px
                    )
                    return


            # 持仓管理

            if pos>0:


                if self.highest_price is None:
                    self.highest_price=c


                self.highest_price=max(
                    self.highest_price,
                    h
                )


                stop_price=o*(1-self.stop_pct())


                # 动态止盈
                if (
                    self.regime=="BULL"
                    and self.entry_price
                    and c/self.entry_price-1>=0.10
                ):

                    if c <= self.highest_price*0.95:

                        self.sell_all(
                            c,
                            "牛市移动止盈"
                        )
                        return



                # 止损

                if l<=stop_price:

                    self.sell_all(
                        stop_price,
                        f"{self.regime}止损"
                    )
                    return



                # 牛市保护趋势

                if (
                    self.regime=="BULL"
                    and not pd.isna(ma20)
                    and c<ma20
                ):

                    self.sell_all(
                        c,
                        "牛市跌破MA20"
                    )
                    return



                # 非牛市保持原规则

                if (
                    self.regime!="BULL"
                    and c<o
                ):

                    self.sell_all(
                        c,
                        "阴线卖出"
                    )
                    return

        finally:
            # 无论是否交易，更新“前一日”OHLC，供次日买入过滤
            self.prev_open = o
            self.prev_close = c

def print_yearly(result: aq.BacktestResult, data: pd.DataFrame) -> None:
    """按自然年对比策略收益 vs 买入持有。"""
    eq = result.equity_curve_daily
    if eq is None or eq.empty:
        print("\n========== 分年对比 ==========\n(无权益曲线)")
        return

    eq = eq.copy()
    if eq.index.tz is not None:
        eq.index = eq.index.tz_convert("Asia/Shanghai")
    eq = eq.sort_index()

    px = data.copy()
    px["date"] = pd.to_datetime(px["date"])
    if px["date"].dt.tz is None:
        px["date"] = px["date"].dt.tz_localize("Asia/Shanghai")
    else:
        px["date"] = px["date"].dt.tz_convert("Asia/Shanghai")
    px_daily = px.set_index("date").sort_index()["close"].resample("D").last().dropna()

    rows = []
    for y in sorted(set(eq.index.year.tolist())):
        eq_y = eq[eq.index.year == y]
        px_y = px_daily[px_daily.index.year == y]
        if eq_y.empty:
            continue
        prev_eq = eq[eq.index.year < y]
        base_eq = float(prev_eq.iloc[-1]) if not prev_eq.empty else float(eq_y.iloc[0])
        end_eq = float(eq_y.iloc[-1])
        strat_pct = (end_eq / base_eq - 1.0) * 100.0

        if not px_y.empty:
            c0 = float(px_y.iloc[0])
            c1 = float(px_y.iloc[-1])
            prev_px = px_daily[px_daily.index.year < y]
            base_px = float(prev_px.iloc[-1]) if not prev_px.empty else c0
            bh_pct = (c1 / base_px - 1.0) * 100.0
        else:
            c0 = c1 = bh_pct = float("nan")

        peak = eq_y.cummax()
        max_dd = float((eq_y / peak - 1.0).min() * 100.0)

        rows.append(
            {
                "年份": y,
                "策略收益%": round(strat_pct, 2),
                "买入持有%": round(bh_pct, 2),
                "超额%": round(strat_pct - bh_pct, 2),
                "年初权益": round(base_eq, 2),
                "年末权益": round(end_eq, 2),
                "年内回撤%": round(max_dd, 2),
                "首收": round(c0, 2),
                "末收": round(c1, 2),
            }
        )

    print("\n========== 分年对比（策略 vs 买入持有）==========")
    print(pd.DataFrame(rows).to_string(index=False))
    print("说明: 收益%=年末/上年年末-1；首年相对当年首日。2026 非整年。")


def main():

    print("加载数据")

    data=fetch_daily(
        SINA_SYMBOL,
        START_DATE,
        END_DATE
    )


    result=aq.run_backtest(
        data=data,
        strategy=BullBearETFStrategy,
        symbols=SYMBOL,
        initial_cash=INITIAL_CASH,
        commission_rate=0.0003,
        stamp_tax_rate=0.001,
        t_plus_one=True,
        lot_size=LOT_SIZE,
        fill_policy=FILL_CLOSE,
        timezone="Asia/Shanghai"
    )


    print(result)
    print_yearly(result, data)

    result.viz.report(
        title="zz500ETF3 动态牛熊策略",
        filename=str(REPORT_PATH),
        show=False,
        market_data=data,
        plot_symbol=SYMBOL,
        curve_freq="D"
    )


if __name__=="__main__":
    main()