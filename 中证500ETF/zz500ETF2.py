"""中证500ETF (510500) — 相对开盘 ±1.2% + 首阳连阳补买.

规则：
  · 买入（空仓可买）：
    1) 当日最高价 ≥ 当日开盘×1.012 → 按开盘+1.2% 买入约 95%
    2) 首阳当日未触及阈值，次日仍为阳线，且相对首阳开盘的两日最高涨幅
       ≥1.2%（max(首阳高,次日高)/首阳开盘-1）→ 按首阳开盘+1.2% 买入
  · 卖出（有仓时，优先级从上到下）：
    1) 止损：当天最低价 ≤ 开盘价×0.988 → 按开盘-1.2% 卖出
    2) 阴线：收盘价 < 开盘价 → 按收盘价卖出
  · 阳线（收盘 > 开盘）：持有不动
  · 卖出后可再次等待下一次冲高 +1.2%
  · 日线近似：high/low 触及即视为盘中按触发价成交
  · 滑点：无

回测：2024-01-01 → 至今；前复权日线；T+1。
运行：python zz500ETF2.py
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import akquant as aq
import akshare as ak
import pandas as pd
from akquant import CurrentClose, Strategy

SYMBOL = "510500"
SYMBOL_NAME = "中证500ETF"
SINA_SYMBOL = "sh510500"
START_DATE = "20240101"
END_DATE = dt.date.today().strftime("%Y%m%d")

INITIAL_CASH = 100_000.0
TARGET_PCT = 0.95
LOT_SIZE = 100
COMMISSION_RATE = 0.0003
STAMP_TAX_RATE = 0.001
# 相对开盘 ±1.2 个点；无滑点
ENTRY_PCT = 0.012
STOP_PCT = 0.012
SLIPPAGE = None  # 不考虑滑点

FILL_CLOSE = CurrentClose()
REPORT_PATH = Path(__file__).with_name("zz500etf2_report.html")


def _fetch_tencent_daily(sina_symbol: str, start: str, end: str) -> pd.DataFrame:
    """腾讯财经前复权日线（按年分段）。"""
    import requests

    start_ts = pd.Timestamp(f"{start[:4]}-{start[4:6]}-{start[6:8]}")
    end_ts = pd.Timestamp(f"{end[:4]}-{end[4:6]}-{end[6:8]}")
    records: list[dict[str, object]] = []
    for year in range(start_ts.year, end_ts.year + 1):
        chunk_start = max(start_ts, pd.Timestamp(year, 1, 1))
        chunk_end = min(end_ts, pd.Timestamp(year, 12, 31))
        if chunk_start > chunk_end:
            continue
        s = chunk_start.strftime("%Y-%m-%d")
        e = chunk_end.strftime("%Y-%m-%d")
        param = f"{sina_symbol},day,{s},{e},640,qfq"
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


def fetch_daily(symbol: str, start: str, end: str) -> pd.DataFrame:
    """前复权日线，清洗为 akquant 标准列；时间戳落到当日 15:00。

    优先级：东财 ETF → 新浪 → 腾讯 → 本地 CSV。
    """
    raw = None
    try:
        raw = ak.fund_etf_hist_em(
            symbol=SYMBOL,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
    except Exception as e:  # noqa: BLE001
        print(f"fund_etf_hist_em 失败: {e}")

    if raw is None or getattr(raw, "empty", True):
        try:
            raw = ak.stock_zh_a_daily(
                symbol=symbol, start_date=start, end_date=end, adjust="qfq"
            )
        except Exception as e:  # noqa: BLE001
            print(f"stock_zh_a_daily 失败: {e}")
            raw = None

    if raw is None or getattr(raw, "empty", True):
        try:
            print(f"回退腾讯日线: {SINA_SYMBOL}")
            raw = _fetch_tencent_daily(SINA_SYMBOL, start, end)
        except Exception as e:  # noqa: BLE001
            print(f"腾讯日线失败: {e}")
            raw = None

    if raw is None or getattr(raw, "empty", True):
        print("回退本地 CSV: 510500_daily_close_zz500etf.csv")
        raw = _load_local_csv(start, end)

    if raw is None or raw.empty:
        raise RuntimeError(f"未获取到日线: {SYMBOL}/{symbol} {start}~{end}")

    df = raw.copy()
    rename = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    df["date"] = pd.to_datetime(df["date"])
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    df["symbol"] = SYMBOL
    df["date"] = df["date"].dt.normalize() + pd.Timedelta(hours=15)
    if df["date"].dt.tz is None:
        df["date"] = df["date"].dt.tz_localize("Asia/Shanghai")
    return df[["date", "open", "high", "low", "close", "volume", "symbol"]].reset_index(
        drop=True
    )


def entry_trigger_price(open_px: float) -> float:
    """开盘价 +ENTRY_PCT。"""
    return round(float(open_px) * (1.0 + ENTRY_PCT), 2)


def stop_trigger_price(open_px: float) -> float:
    """开盘价 -STOP_PCT。"""
    return round(float(open_px) * (1.0 - STOP_PCT), 2)


class OpenBreak3Strategy(Strategy):
    """相对开盘 +1.2%买入（含首阳连阳补买）；-1.2%止损或阴线收盘卖；阳线持有。"""

    def on_start(self) -> None:
        self.subscribe(SYMBOL)
        self.lot_size = LOT_SIZE
        self.armed = True
        self.entry_price: float | None = None
        # 首阳未触阈值：等待次日连阳合算涨幅
        self.pending_first_open: float | None = None
        self.pending_first_high: float | None = None
        self.pending_first_day: str | None = None
        self.log(
            f"{SYMBOL_NAME}({SYMBOL}) 开盘±{ENTRY_PCT*100:.1f}% "
            f"(+买/首阳连阳补买/-止损，阴线收盘出，阳线持有) | "
            f"无滑点 | {START_DATE}~{END_DATE}"
        )

    def _clear_pending(self) -> None:
        self.pending_first_open = None
        self.pending_first_high = None
        self.pending_first_day = None

    def _hold_pnl_pct(self, mark_px: float) -> float | None:
        """相对策略买入价的持有收益%（未计入滑点）。"""
        if self.entry_price is None or self.entry_price <= 0:
            return None
        return (float(mark_px) / float(self.entry_price) - 1.0) * 100.0

    def _fmt_hold(self, mark_px: float) -> str:
        pct = self._hold_pnl_pct(mark_px)
        if pct is None:
            return "持有收益=n/a"
        return f"持有收益={pct:+.2f}%"

    def _buy(
        self,
        *,
        day: str,
        entry_px: float,
        reason: str,
        detail: str,
    ) -> None:
        self.order_target_percent(
            symbol=SYMBOL,
            target_percent=TARGET_PCT,
            price=entry_px,
            fill_mode=FILL_CLOSE,
            slippage=SLIPPAGE,
        )
        self.armed = False
        self.entry_price = entry_px
        self._clear_pending()
        self.log(f"{day} {reason} @ {entry_px:.2f} {detail} 持有收益=+0.00%")

    def _exit_all(
        self, *, day: str, avail: float, pos: float, price: float, reason: str
    ) -> bool:
        hold_txt = self._fmt_hold(price)
        if avail > 0:
            self.sell(
                SYMBOL,
                avail,
                price=price,
                fill_mode=FILL_CLOSE,
                slippage=SLIPPAGE,
            )
            self.log(
                f"{day} {reason} qty={avail:.0f} @ {price:.2f} {hold_txt}"
            )
            self.armed = True
            self.entry_price = None
            self._clear_pending()
            return True
        if pos > 0:
            self.log(
                f"{day} {reason} 但 T+1 不可用 avail=0 pos={pos:.0f} {hold_txt}"
            )
        return False

    def on_bar(self, bar) -> None:
        if bar.symbol != SYMBOL:
            return

        o = float(bar.open)
        h = float(bar.high)
        low = float(bar.low)
        c = float(bar.close)
        day = self.to_local_time(bar.timestamp).strftime("%Y-%m-%d")
        pos = float(self.get_position(SYMBOL))

        entry_px = entry_trigger_price(o)
        stop_px = stop_trigger_price(o)
        hit_entry = h + 1e-12 >= entry_px
        hit_stop = low - 1e-12 <= stop_px
        yin = c < o  # 阴线
        yang = c > o  # 阳线

        # 1) 空仓买入
        if self.armed and pos <= 0:
            bought = False

            # 1a) 当日相对开盘触及阈值
            if hit_entry:
                self._buy(
                    day=day,
                    entry_px=entry_px,
                    reason=f"开盘+{ENTRY_PCT*100:.1f}%买入",
                    detail=f"(open={o:.2f} high={h:.2f})",
                )
                bought = True

            # 1b) 首阳未触 → 次日连阳：相对首阳开盘的两日最高涨幅达标
            elif (
                self.pending_first_open is not None
                and self.pending_first_high is not None
                and yang
            ):
                combo_high = max(float(self.pending_first_high), h)
                combo_entry = entry_trigger_price(float(self.pending_first_open))
                combo_pct = (combo_high / float(self.pending_first_open) - 1.0) * 100.0
                if combo_high + 1e-12 >= combo_entry:
                    self._buy(
                        day=day,
                        entry_px=combo_entry,
                        reason=f"首阳连阳补买+{ENTRY_PCT*100:.1f}%",
                        detail=(
                            f"(首阳{self.pending_first_day} open={self.pending_first_open:.2f} "
                            f"两日最高={combo_high:.2f} 合涨={combo_pct:+.2f}%)"
                        ),
                    )
                    bought = True
                else:
                    # 次日连阳仍未达标：以今日为新的首阳候选
                    self.pending_first_open = o
                    self.pending_first_high = h
                    self.pending_first_day = day
            elif yin or not yang:
                # 断阳：清空首阳等待
                self._clear_pending()

            # 1c) 当日阳线未触阈值 → 记为首阳，等次日
            if (
                not bought
                and self.armed
                and yang
                and not hit_entry
                and self.pending_first_open is None
            ):
                self.pending_first_open = o
                self.pending_first_high = h
                self.pending_first_day = day
                self.log(
                    f"{day} 首阳未触阈值 "
                    f"(open={o:.2f} high={h:.2f} "
                    f"涨幅={(h/o-1.0)*100:.2f}% < {ENTRY_PCT*100:.1f}%)，等次日连阳"
                )

        # 2) 有仓卖出：止损优先，其次阴线收盘出；阳线不动
        pos = float(self.get_position(SYMBOL))
        avail = float(self.get_available_position(SYMBOL))
        if pos <= 0 and avail <= 0:
            return

        if hit_stop:
            self._exit_all(
                day=day,
                avail=avail,
                pos=pos,
                price=stop_px,
                reason=f"开盘-{STOP_PCT*100:.1f}%止损(low={low:.2f})",
            )
            return

        if yin:
            self._exit_all(
                day=day,
                avail=avail,
                pos=pos,
                price=c,
                reason="阴线收盘卖出",
            )
            return

        if yang:
            # 阳线持有不动
            return


def _metric(metrics_df: pd.DataFrame, name: str) -> float:
    if name not in metrics_df.index:
        return float("nan")
    return float(metrics_df.loc[name, "value"])


def print_summary(result: aq.BacktestResult, data: pd.DataFrame) -> None:
    m = result.metrics_df
    c0 = float(data.iloc[0]["close"])
    c1 = float(data.iloc[-1]["close"])
    bh_pct = (c1 / c0 - 1.0) * 100.0

    print("\n========== 回测摘要 ==========")
    print(f"标的: {SYMBOL_NAME} ({SYMBOL})")
    print(f"区间: {data['date'].iloc[0]} → {data['date'].iloc[-1]}")
    print(f"日线根数: {len(data)}")
    print(f"买入: ①当日high≥open×{1+ENTRY_PCT:.3f}@开盘+{ENTRY_PCT*100:.1f}%；")
    print(
        f"     ②首阳未触且次日连阳，"
        f"max(两日高)/首阳开盘-1≥{ENTRY_PCT*100:.1f}%@首阳开盘+{ENTRY_PCT*100:.1f}%"
    )
    print(
        f"卖出: ①low<=open×{1-STOP_PCT:.3f}@开盘-{STOP_PCT*100:.1f}%；"
        f"②阴线@收盘；阳线持有"
    )
    print(f"滑点: 无")
    print(f"总盈亏: {_metric(m, 'total_pnl'):.2f}")
    print(f"累计收益%: {_metric(m, 'total_return_pct'):.4f}")
    print(f"最大回撤%: {_metric(m, 'max_drawdown_pct'):.4f}")
    print(f"胜率%: {_metric(m, 'win_rate'):.4f}")
    print(f"闭环交易: {_metric(m, 'closed_trade_count'):.0f}")
    print(f"夏普: {_metric(m, 'sharpe_ratio'):.4f}")
    print(f"期末市值: {_metric(m, 'end_market_value'):.2f}")
    print(f"买入持有(首收→末收): {bh_pct:.2f}%  ({c0:.2f} → {c1:.2f})")
    print_yearly(result, data)

    if not result.executions_df.empty:
        print("\n--- 成交明细（节选前 40）---")
        cols = [
            c
            for c in ("symbol", "side", "quantity", "price", "commission", "timestamp")
            if c in result.executions_df.columns
        ]
        print(result.executions_df[cols].head(40).to_string(index=False))
        print(f"... 共 {len(result.executions_df)} 笔成交")


def print_yearly(result: aq.BacktestResult, data: pd.DataFrame) -> None:
    """按自然年输出策略收益 / 买入持有 / 成交与闭环交易。"""
    eq = result.equity_curve_daily
    if eq is None or eq.empty:
        print("\n========== 分年数据 ==========")
        print("(无权益曲线，跳过)")
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
    px = px.set_index("date").sort_index()
    px_daily = px["close"].resample("D").last().dropna()

    exec_df = result.executions_df
    trades_df = result.trades_df if hasattr(result, "trades_df") else pd.DataFrame()

    years = sorted(set(eq.index.year.tolist()) | set(px_daily.index.year.tolist()))
    rows: list[dict[str, Any]] = []
    for y in years:
        eq_y = eq[eq.index.year == y]
        px_y = px_daily[px_daily.index.year == y]
        if eq_y.empty:
            continue
        start_eq = float(eq_y.iloc[0])
        end_eq = float(eq_y.iloc[-1])
        # 用年末相对上年年末；首年用年初首值
        prev = eq[eq.index.year < y]
        base_eq = float(prev.iloc[-1]) if not prev.empty else start_eq
        strat_pct = (end_eq / base_eq - 1.0) * 100.0 if base_eq > 0 else float("nan")

        if not px_y.empty:
            c0 = float(px_y.iloc[0])
            c1 = float(px_y.iloc[-1])
            # 与策略一致：首年用当年首收，后续用上年最后收盘
            prev_px = px_daily[px_daily.index.year < y]
            base_px = float(prev_px.iloc[-1]) if not prev_px.empty else c0
            bh_pct = (c1 / base_px - 1.0) * 100.0 if base_px > 0 else float("nan")
        else:
            c0 = c1 = bh_pct = float("nan")

        n_buy = n_sell = 0
        if exec_df is not None and not exec_df.empty and "timestamp" in exec_df.columns:
            ts = pd.to_datetime(exec_df["timestamp"])
            if getattr(ts.dt, "tz", None) is not None:
                ts = ts.dt.tz_convert("Asia/Shanghai")
            mask = ts.dt.year == y
            side = exec_df.loc[mask, "side"].astype(str).str.lower()
            n_buy = int((side == "buy").sum())
            n_sell = int((side == "sell").sum())

        n_closed = 0
        win_rate = float("nan")
        if trades_df is not None and not trades_df.empty:
            # 闭环交易按平仓时间归年
            close_col = next(
                (c for c in ("exit_time", "close_time", "end_time", "timestamp") if c in trades_df.columns),
                None,
            )
            pnl_col = next(
                (c for c in ("pnl", "realized_pnl", "profit") if c in trades_df.columns),
                None,
            )
            if close_col is not None:
                cts = pd.to_datetime(trades_df[close_col])
                if getattr(cts.dt, "tz", None) is not None:
                    cts = cts.dt.tz_convert("Asia/Shanghai")
                tmask = cts.dt.year == y
                n_closed = int(tmask.sum())
                if pnl_col is not None and n_closed > 0:
                    pnls = pd.to_numeric(trades_df.loc[tmask, pnl_col], errors="coerce")
                    wins = (pnls > 0).sum()
                    win_rate = float(wins) / float(n_closed) * 100.0

        # 年内最大回撤（相对当年权益峰值）
        peak = eq_y.cummax()
        dd = (eq_y / peak - 1.0) * 100.0
        max_dd = float(dd.min()) if not dd.empty else float("nan")

        rows.append(
            {
                "年份": y,
                "策略收益%": round(strat_pct, 2),
                "买入持有%": round(bh_pct, 2) if bh_pct == bh_pct else None,
                "年初权益": round(base_eq, 2),
                "年末权益": round(end_eq, 2),
                "年内回撤%": round(max_dd, 2),
                "买入笔数": n_buy,
                "卖出笔数": n_sell,
                "闭环交易": n_closed,
                "胜率%": None if win_rate != win_rate else round(win_rate, 2),
                "首收": None if c0 != c0 else round(c0, 2),
                "末收": None if c1 != c1 else round(c1, 2),
            }
        )

    print("\n========== 分年数据 ==========")
    if not rows:
        print("(无)")
        return
    print(pd.DataFrame(rows).to_string(index=False))
    print("说明: 策略收益%=该年末权益/上年年末权益-1；首年相对当年首日权益。")
    print("     买入持有%=该年末收盘/上年年末收盘-1（首年用当年首收）。")

def main() -> None:
    print(f"akquant={getattr(aq, '__version__', '?')}")
    print(f"拉取 {SYMBOL_NAME}({SYMBOL}) 日线 {START_DATE} → {END_DATE} ...")
    daily = fetch_daily(SINA_SYMBOL, START_DATE, END_DATE)
    print(
        f"日线数: {len(daily)}，"
        f"区间: {daily['date'].iloc[0]} → {daily['date'].iloc[-1]}"
    )

    result = aq.run_backtest(
        data=daily,
        strategy=OpenBreak3Strategy,
        symbols=SYMBOL,
        initial_cash=INITIAL_CASH,
        commission_rate=COMMISSION_RATE,
        stamp_tax_rate=STAMP_TAX_RATE,
        t_plus_one=True,
        lot_size=LOT_SIZE,
        fill_policy=FILL_CLOSE,
        slippage=SLIPPAGE,
        timezone="Asia/Shanghai",
        show_progress=False,
    )

    print("\n=== Backtest Result ===")
    print(result)
    print_summary(result, daily)

    print(f"\n生成 HTML: {REPORT_PATH}")
    result.viz.report(
        title=(
            f"{SYMBOL_NAME} 开盘±{ENTRY_PCT*100:.1f}%+首阳连阳补买 "
            f"无滑点 ({START_DATE}~{END_DATE})"
        ),
        filename=str(REPORT_PATH),
        show=True,
        market_data=daily,
        plot_symbol=SYMBOL,
        curve_freq="D",
    )
    print(f"报告已生成: {REPORT_PATH}")


if __name__ == "__main__":
    main()
