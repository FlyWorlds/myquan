"""akquant 回测：OpenBreak3Strategy 与报告。"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import akquant as aq
import akshare as ak
import pandas as pd
from akquant import CurrentClose, Strategy

from strategy.minute import fetch_minute_1m
from strategy.open_break import (
    ENTRY_PCT,
    GAP_DOWN_EXIT_HOUR,
    GAP_DOWN_EXIT_MINUTE,
    PREV_SMALL_YANG_PCT,
    STOP_PCT,
    TICK_SIZE,
    build_gap_down_945_map,
    entry_trigger_price,
    has_double_yang_before,
    is_yin,
    is_yang,
    prev_day_allows_entry,
    stop_trigger_price,
)


def fetch_daily(symbol: str, start: str, end: str) -> pd.DataFrame:
    raw: pd.DataFrame | None = None
    try:
        raw = ak.stock_zh_a_daily(
            symbol=symbol, start_date=start, end_date=end, adjust="qfq"
        )
    except Exception:
        raw = None
    if raw is None or raw.empty:
        code = symbol[2:] if len(symbol) > 2 and symbol[:2] in ("sh", "sz") else symbol
        raw = ak.fund_etf_hist_em(
            symbol=code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
    if raw is None or raw.empty:
        raise RuntimeError(f"未获取到日线: {symbol} {start}~{end}")

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
    if "date" not in df.columns and "日期" in df.columns:
        df = df.rename(columns={"日期": "date"})
    df["date"] = pd.to_datetime(df["date"])
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    df["symbol"] = symbol
    df["date"] = df["date"].dt.normalize() + pd.Timedelta(hours=15)
    if df["date"].dt.tz is None:
        df["date"] = df["date"].dt.tz_localize("Asia/Shanghai")
    return df[["date", "open", "high", "low", "close", "volume", "symbol"]].reset_index(
        drop=True
    )


class OpenBreak3Strategy(Strategy):
    """相对开盘 ±pct 买入；低开945未翻红全清/止损/阴线卖出。"""

    symbol: str = "sh600552"
    symbol_name: str = "凯盛科技"
    target_pct: float = 0.95
    lot_size: int = 100
    start_date: str = "20250101"
    end_date: str = ""
    slippage_value: float = 0.001
    gap_down_945_map: dict[str, dict[str, float | str]] = {}
    enable_gap945: bool = True
    entry_pct: float = ENTRY_PCT
    stop_pct: float = STOP_PCT
    prev_small_yang_pct: float = PREV_SMALL_YANG_PCT
    tick: float = TICK_SIZE
    t0: bool = False

    def on_start(self) -> None:
        self.subscribe(self.symbol)
        self.lot_size = self.lot_size
        self.armed = True
        self.entry_price: float | None = None
        self.prev_open: float | None = None
        self.prev_close: float | None = None
        self.prev2_open: float | None = None
        self.prev2_close: float | None = None
        self.buy_day: str | None = None
        n_gap = len(self.gap_down_945_map)
        self.log(
            f"{self.symbol_name}({self.symbol}) 开盘±{self.entry_pct*100:.1f}% "
            f"(+买/-止损，低开{GAP_DOWN_EXIT_HOUR:02d}:{GAP_DOWN_EXIT_MINUTE:02d}未翻红全清，阴线收盘出) | "
            f"前日须阴线或小阳(<{self.prev_small_yang_pct*100:.1f}%)，禁前面双阳 | "
            f"低开规则日历日={n_gap} | "
            f"佣金万0.854 滑点{self.slippage_value*100:.1f}% | "
            f"{self.start_date}~{self.end_date}"
        )

    def _hold_pnl_pct(self, mark_px: float) -> float | None:
        if self.entry_price is None or self.entry_price <= 0:
            return None
        return (float(mark_px) / float(self.entry_price) - 1.0) * 100.0

    def _fmt_hold(self, mark_px: float) -> str:
        pct = self._hold_pnl_pct(mark_px)
        if pct is None:
            return "持有收益=n/a"
        return f"持有收益={pct:+.2f}%"

    def _sync_position_state(self) -> float:
        pos = float(self.get_position(self.symbol))
        if pos <= 0:
            self.armed = True
            self.entry_price = None
            self.buy_day = None
        else:
            self.armed = False
        return pos

    def _exit_all(
        self, *, day: str, avail: float, pos: float, price: float, reason: str
    ) -> bool:
        hold_txt = self._fmt_hold(price)
        if avail > 0:
            self.sell(self.symbol, avail, price=price)
            self.log(f"{day} {reason} qty={avail:.0f} 限价={price:.2f} {hold_txt}")
            self.armed = True
            self.entry_price = None
            self.buy_day = None
            return True
        if pos > 0:
            self.log(
                f"{day} {reason} 跳过(T+1 买入日不可卖) avail=0 pos={pos:.0f} {hold_txt}"
            )
        return False

    def _roll_prev_bars(self, open_px: float, close_px: float) -> None:
        self.prev2_open = self.prev_open
        self.prev2_close = self.prev_close
        self.prev_open = open_px
        self.prev_close = close_px

    def on_bar(self, bar) -> None:
        if bar.symbol != self.symbol:
            return

        o = float(bar.open)
        h = float(bar.high)
        low = float(bar.low)
        c = float(bar.close)
        day = self.to_local_time(bar.timestamp).strftime("%Y-%m-%d")

        bought_today = False
        try:
            pos = self._sync_position_state()
            entry_px = entry_trigger_price(o, entry_pct=self.entry_pct, tick=self.tick)
            stop_px = stop_trigger_price(o, stop_pct=self.stop_pct, tick=self.tick)
            hit_entry = h + 1e-12 >= entry_px
            hit_stop = low <= stop_px + 1e-12
            yin = is_yin(o, c)

            if self.armed and pos <= 0 and hit_entry:
                can_buy = (
                    self.prev_open is not None
                    and self.prev_close is not None
                    and prev_day_allows_entry(
                        self.prev_open,
                        self.prev_close,
                        prev_small_yang_pct=self.prev_small_yang_pct,
                    )
                    and not has_double_yang_before(
                        self.prev2_open,
                        self.prev2_close,
                        self.prev_open,
                        self.prev_close,
                    )
                )
                if can_buy:
                    self.order_target_percent(
                        symbol=self.symbol,
                        target_percent=self.target_pct,
                        price=entry_px,
                    )
                    self.armed = False
                    self.entry_price = entry_px
                    self.buy_day = day
                    bought_today = True
                    self.log(
                        f"{day} 开盘+{self.entry_pct*100:.1f}%买入 限价={entry_px:.2f} "
                        f"(open={o:.2f} high={h:.2f}) 持有收益=+0.00%"
                    )
                elif self.prev_open is not None and self.prev_close is not None:
                    if not prev_day_allows_entry(
                        self.prev_open,
                        self.prev_close,
                        prev_small_yang_pct=self.prev_small_yang_pct,
                    ):
                        self.log(
                            f"{day} 触及买点但前日不符(须阴线或小阳"
                            f"<{self.prev_small_yang_pct*100:.1f}%) skip"
                        )
                    elif has_double_yang_before(
                        self.prev2_open,
                        self.prev2_close,
                        self.prev_open,
                        self.prev_close,
                    ):
                        self.log(f"{day} 触及买点但前面双阳 skip")

            if not self.t0 and (bought_today or self.buy_day == day):
                return

            pos = float(self.get_position(self.symbol))
            avail = float(self.get_available_position(self.symbol))
            if pos <= 0 and avail <= 0:
                return

            gap = self.gap_down_945_map.get(day) if self.enable_gap945 else None
            if gap is not None:
                exit_px = float(gap["exit_px"])
                src = str(gap.get("source") or "1m")
                prev_c = float(gap["prev_close"])
                self._exit_all(
                    day=day,
                    avail=avail,
                    pos=pos,
                    price=exit_px,
                    reason=(
                        f"低开{GAP_DOWN_EXIT_HOUR:02d}:{GAP_DOWN_EXIT_MINUTE:02d}未翻红全清"
                        f"(open={o:.2f}<prev={prev_c:.2f} exit945={exit_px:.2f} {src})"
                    ),
                )
                return

            if hit_stop:
                self._exit_all(
                    day=day,
                    avail=avail,
                    pos=pos,
                    price=stop_px,
                    reason=f"开盘-{self.stop_pct*100:.1f}%止损(open={o:.2f} low={low:.2f})",
                )
                return

            if yin:
                self._exit_all(
                    day=day,
                    avail=avail,
                    pos=pos,
                    price=float(c),
                    reason="阴线收盘卖出",
                )
        finally:
            self._roll_prev_bars(o, c)


def _metric(metrics_df: pd.DataFrame, name: str) -> float:
    if name not in metrics_df.index:
        return float("nan")
    return float(metrics_df.loc[name, "value"])


def print_summary(
    result: aq.BacktestResult,
    data: pd.DataFrame,
    *,
    symbol_name: str,
    symbol: str,
    initial_cash: float,
    commission_rate: float,
    stamp_tax_rate: float,
    slippage_value: float,
    entry_pct: float = ENTRY_PCT,
    stop_pct: float = STOP_PCT,
    prev_small_yang_pct: float = PREV_SMALL_YANG_PCT,
) -> None:
    m = result.metrics_df
    c0 = float(data.iloc[0]["close"])
    c1 = float(data.iloc[-1]["close"])
    bh_pct = (c1 / c0 - 1.0) * 100.0

    print("\n========== 回测摘要 ==========")
    print(f"标的: {symbol_name} ({symbol})")
    print(f"区间: {data['date'].iloc[0]} → {data['date'].iloc[-1]}")
    print(f"日线根数: {len(data)}")
    print(f"买入: high>=ceil(open×{1+entry_pct:.3f})，止损 low<=floor(open×{1-stop_pct:.3f})")
    print(
        f"      前日须阴线或收盘严格<open×{1+prev_small_yang_pct:.3f}，禁前面双阳"
    )
    print(
        f"卖出: ①低开{GAP_DOWN_EXIT_HOUR:02d}:{GAP_DOWN_EXIT_MINUTE:02d}"
        f"前未翻红(high<昨收)则按09:45分钟收盘价全清；②止损@触发价清仓；③阴线@收盘；阳/十字持有；买入日不卖"
    )
    print(f"佣金: 万0.854 ({commission_rate})；印花税(卖): {stamp_tax_rate*100:.1f}%")
    print(f"滑点: {slippage_value*100:.1f}%")
    print(f"总盈亏: {_metric(m, 'total_pnl'):.2f}")
    print(f"累计收益%: {_metric(m, 'total_return_pct'):.4f}")
    print(f"最大回撤%: {_metric(m, 'max_drawdown_pct'):.4f}")
    print(f"胜率%: {_metric(m, 'win_rate'):.4f}")
    print(f"闭环交易: {_metric(m, 'closed_trade_count'):.0f}")
    print(f"夏普: {_metric(m, 'sharpe_ratio'):.4f}")
    print(f"期末市值: {_metric(m, 'end_market_value'):.2f}")
    print(f"买入持有(首收→末收): {bh_pct:.2f}%  ({c0:.2f} → {c1:.2f})")
    print_yearly(result, data, initial_cash=initial_cash)

    if not result.executions_df.empty:
        print("\n--- 成交明细（节选前 40）---")
        cols = [
            c
            for c in ("symbol", "side", "quantity", "price", "commission", "timestamp")
            if c in result.executions_df.columns
        ]
        print(result.executions_df[cols].head(40).to_string(index=False))
        print(f"... 共 {len(result.executions_df)} 笔成交")


def print_yearly(
    result: aq.BacktestResult,
    data: pd.DataFrame,
    *,
    initial_cash: float,
) -> None:
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
        end_eq = float(eq_y.iloc[-1])
        prev = eq[eq.index.year < y]
        base_eq = float(prev.iloc[-1]) if not prev.empty else initial_cash
        strat_pct = (end_eq / base_eq - 1.0) * 100.0 if base_eq > 0 else float("nan")

        if not px_y.empty:
            c0 = float(px_y.iloc[0])
            c1 = float(px_y.iloc[-1])
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
            close_col = next(
                (
                    c
                    for c in ("exit_time", "close_time", "end_time", "timestamp")
                    if c in trades_df.columns
                ),
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
    print("说明: 策略收益%=该年末权益/上年年末权益-1；首年相对 INITIAL_CASH。")
    print("     买入持有%=该年末收盘/上年年末收盘-1（首年用当年首收）。")
