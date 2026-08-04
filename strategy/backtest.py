"""akquant 回测：OpenBreak3Strategy 与报告。"""

from __future__ import annotations

from typing import Any

import akquant as aq
import pandas as pd
from akquant import CurrentClose, Strategy

from strategy.open_break import (
    ENTRY_PCT,
    PREV_SMALL_YANG_PCT,
    STOP_PCT,
    TICK_SIZE,
    entry_trigger_price,
    has_double_yang_before,
    is_yang,
    limit_down_state,
    prev_day_allows_entry,
    stop_trigger_price,
)


class OpenBreak3Strategy(Strategy):
    """相对开盘±pct买入；仅保留止损全清。"""

    symbol: str = "sh600552"
    symbol_name: str = "凯盛科技"
    target_pct: float = 0.95
    lot_size: int = 100
    start_date: str = "20250101"
    end_date: str = ""
    slippage_value: float = 0.001
    entry_pct: float = ENTRY_PCT
    stop_pct: float = STOP_PCT
    prev_small_yang_pct: float = PREV_SMALL_YANG_PCT
    tick: float = TICK_SIZE
    limit_down_pct: float = 0.10
    t0: bool = False
    # today_open | prev_open_on_small_yang
    entry_ref: str = "today_open"
    # yin_or_small_yang | yin_only（小阳次日不买）
    prev_entry_mode: str = "yin_or_small_yang"
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
        entry_txt = (
            "买点=前日小阳开盘×(1+pct)"
            if self.entry_ref == "prev_open_on_small_yang"
            else "买点=今日开盘×(1+pct)"
        )
        prev_txt = (
            "前日仅阴线（小阳次日不买）"
            if self.prev_entry_mode == "yin_only"
            else f"前日须阴线或小阳(<{self.prev_small_yang_pct*100:.1f}%)"
        )
        self.log(
            f"{self.symbol_name}({self.symbol}) 开盘±{self.entry_pct*100:.1f}% "
            f"(+买/-止损，仅止损全清) | "
            f"{prev_txt}，禁前面双阳 | "
            f"{entry_txt} | "
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

    def _can_enter_by_prev_filter(self) -> bool:
        return (
            self.prev_open is not None
            and self.prev_close is not None
            and prev_day_allows_entry(
                self.prev_open,
                self.prev_close,
                prev_small_yang_pct=self.prev_small_yang_pct,
                prev_entry_mode=self.prev_entry_mode,
            )
            and not has_double_yang_before(
                self.prev2_open,
                self.prev2_close,
                self.prev_open,
                self.prev_close,
            )
        )

    def _try_enter(
        self,
        *,
        day: str,
        entry_px: float,
        open_px: float,
        high_px: float,
    ) -> bool:
        """空仓且过滤通过时按目标仓位限价买入。"""
        pos = float(self.get_position(self.symbol))
        if (not self.armed) or pos > 0:
            return False
        if not self._can_enter_by_prev_filter():
            return False
        tgt = float(self.target_pct)
        self.order_target_percent(
            symbol=self.symbol,
            target_percent=tgt,
            price=entry_px,
        )
        self.armed = False
        self.entry_price = entry_px
        self.buy_day = day
        self.log(
            f"{day} 开盘+{self.entry_pct*100:.1f}%买入(全仓"
            f" target={tgt*100:.1f}%) 限价={entry_px:.2f} "
            f"(open={open_px:.2f} high={high_px:.2f}) 持有收益=+0.00%"
        )
        return True

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
            # 买点基准：默认今日开盘；优化版在前日小阳时改用前日开盘
            entry_base = o
            if (
                self.entry_ref == "prev_open_on_small_yang"
                and self.prev_open is not None
                and self.prev_close is not None
                and is_yang(self.prev_open, self.prev_close)
                and prev_day_allows_entry(
                    self.prev_open,
                    self.prev_close,
                    prev_small_yang_pct=self.prev_small_yang_pct,
                )
            ):
                entry_base = float(self.prev_open)
            entry_px = entry_trigger_price(
                entry_base, entry_pct=self.entry_pct, tick=self.tick
            )
            stop_px = stop_trigger_price(o, stop_pct=self.stop_pct, tick=self.tick)
            hit_entry = h + 1e-12 >= entry_px
            hit_stop = low <= stop_px + 1e-12

            if self.armed and pos <= 0 and hit_entry:
                if self._try_enter(
                    day=day, entry_px=entry_px, open_px=o, high_px=h
                ):
                    bought_today = True
                elif self.prev_open is not None and self.prev_close is not None:
                    if not prev_day_allows_entry(
                        self.prev_open,
                        self.prev_close,
                        prev_small_yang_pct=self.prev_small_yang_pct,
                        prev_entry_mode=self.prev_entry_mode,
                    ):
                        need = (
                            "须阴线(小阳次日不买)"
                            if self.prev_entry_mode == "yin_only"
                            else f"须阴线或小阳<{self.prev_small_yang_pct*100:.1f}%"
                        )
                        self.log(f"{day} 触及买点但前日不符({need}) skip")
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

            if hit_stop:
                limit_state = limit_down_state(
                    prev_close=self.prev_close,
                    open_px=o,
                    high_px=h,
                    low_px=low,
                    close_px=c,
                    limit_down_pct=self.limit_down_pct,
                    tick=self.tick,
                )
                if bool(limit_state["locked"]):
                    self.log(
                        f"{day} 一字跌停封单，止损不可成交 "
                        f"(limit={float(limit_state['limit_px']):.2f}) 持仓延续"
                    )
                    return
                exit_px = float(
                    limit_state["limit_px"]
                    if bool(limit_state["opened"])
                    else stop_px
                )
                reason = (
                    f"跌停开板按跌停价止损"
                    f"(limit={exit_px:.2f} open={o:.2f} low={low:.2f})"
                    if bool(limit_state["opened"])
                    else (
                        f"开盘-{self.stop_pct*100:.1f}%止损"
                        f"(open={o:.2f} low={low:.2f})"
                    )
                )
                self._exit_all(
                    day=day,
                    avail=avail,
                    pos=pos,
                    price=exit_px,
                    reason=reason,
                )
                return
        finally:
            self._roll_prev_bars(o, c)


def _metric(metrics_df: pd.DataFrame, name: str) -> float:
    if name not in metrics_df.index:
        return float("nan")
    return float(metrics_df.loc[name, "value"])


metric = _metric


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
    print("卖出: 仅止损@触发价清仓；未触止损继续持有；买入日不卖")
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
    print_monthly(result, data, initial_cash=initial_cash)

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
    prepared = _prepare_equity_and_close(result, data)
    if prepared is None:
        print("\n========== 分年数据 ==========")
        print("(无权益曲线，跳过)")
        return

    eq, px_daily = prepared
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


def _prepare_equity_and_close(
    result: aq.BacktestResult,
    data: pd.DataFrame,
) -> tuple[pd.Series, pd.Series] | None:
    eq = result.equity_curve_daily
    if eq is None or eq.empty:
        return None

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
    return eq, px_daily


def monthly_returns_df(
    result: aq.BacktestResult,
    data: pd.DataFrame,
    *,
    initial_cash: float,
) -> pd.DataFrame:
    prepared = _prepare_equity_and_close(result, data)
    if prepared is None:
        return pd.DataFrame(columns=["月份", "策略收益%", "持有收益%"])

    eq, px_daily = prepared
    months = sorted(
        set(eq.index.to_period("M").astype(str).tolist())
        | set(px_daily.index.to_period("M").astype(str).tolist())
    )
    rows: list[dict[str, Any]] = []
    for month in months:
        period = pd.Period(month, freq="M")
        eq_m = eq[eq.index.to_period("M") == period]
        px_m = px_daily[px_daily.index.to_period("M") == period]
        if eq_m.empty and px_m.empty:
            continue

        if not eq_m.empty:
            end_eq = float(eq_m.iloc[-1])
            prev_eq = eq[eq.index.to_period("M") < period]
            base_eq = float(prev_eq.iloc[-1]) if not prev_eq.empty else initial_cash
            strat_pct = (end_eq / base_eq - 1.0) * 100.0 if base_eq > 0 else float("nan")
        else:
            strat_pct = float("nan")

        if not px_m.empty:
            c0 = float(px_m.iloc[0])
            c1 = float(px_m.iloc[-1])
            prev_px = px_daily[px_daily.index.to_period("M") < period]
            base_px = float(prev_px.iloc[-1]) if not prev_px.empty else c0
            bh_pct = (c1 / base_px - 1.0) * 100.0 if base_px > 0 else float("nan")
        else:
            bh_pct = float("nan")

        rows.append(
            {
                "月份": month,
                "策略收益%": round(strat_pct, 2) if strat_pct == strat_pct else None,
                "持有收益%": round(bh_pct, 2) if bh_pct == bh_pct else None,
            }
        )
    return pd.DataFrame(rows)


def print_monthly(
    result: aq.BacktestResult,
    data: pd.DataFrame,
    *,
    initial_cash: float,
) -> None:
    df = monthly_returns_df(result, data, initial_cash=initial_cash)
    print("\n========== 分月数据 ==========")
    if df.empty:
        print("(无)")
        return
    print(df.to_string(index=False))
    print("说明: 策略收益%=该月末权益/上月末权益-1；首月相对 INITIAL_CASH。")
    print("     持有收益%=该月末收盘/上月末收盘-1（首月用当月首收）。")
