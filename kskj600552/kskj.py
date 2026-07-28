"""凯盛科技 (sh600552) — 相对开盘 ±2.5% 策略.

规则：
  · 买入：空仓可买时，当天最高价 ≥ 触发价（open×1.025 向上取整到 0.01）→ 限价买入约 95%
    - 前一日须阴线，或收盘严格低于 open×1.025（小阳线）
    - 前一日与前二日不能连续两根阳线（前面双阳不买）
  · 卖出（有仓时，优先级从上到下；买入当日不执行任何卖出判断）：
    1) 止损：low ≤ 触发价（open×0.975 向下取整到 0.01）→ 限价止损
    2) 阴线：收盘价 < 开盘价 → 按收盘价卖出
  · 阳线（收盘 > 开盘）：持有；十字星（收盘 = 开盘）：持有
  · 卖出后可再次等待下一次冲高 +2.5%
  · 日线近似：high/low 触及即视为盘中按触发价成交
  · 滑点：买卖各 0.1%，仅在 run_backtest(slippage=) 配置一次
  · 佣金：万 0.854（买卖双向）；印花税：卖出 0.1%
  · 限价对齐：买入触发价 ceil、止损触发价 floor（至少达到 ±2.5%）

回测：2025-01-01 → 至今；前复权日线；T+1。
运行：python kskj.py

K 线形态边界（相对当日 open，非前收）：
  · 十字星 c==o：既不阴也不阳 → 持有，不触发阴线卖出
  · 大幅低开但收阳 c>o：若 low 触止损则先止损；否则持有
  · 高开低走 c<o（收盘可仍高于前收）：按阴线规则收盘卖出

AKQuant 成交说明：
  · run_backtest(fill_policy=CurrentClose) 表示「当根 K 线周期内撮合」
  · 订单显式传 price= 时为限价单：触价后按 limit±全局 slippage 成交，非 bar.close
  · 滑点/commission 仅走 run_backtest 全局参数，订单层不再重复传
  · tick_size=0.01 交给引擎校验最小变动价位
  非 akquant：fetch_daily 用 akshare；形态过滤与跳空定价为策略自写逻辑。
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
from typing import Any

import akquant as aq  # [akquant] 回测入口 run_backtest、BacktestResult
import akshare as ak  # 非 akquant：仅用于 fetch_daily 拉历史 K 线
import pandas as pd
from akquant import CurrentClose, Strategy  # [akquant] 策略基类、成交模式

SYMBOL = "sh600552"
SYMBOL_NAME = "凯盛科技"
START_DATE = "20250101"
END_DATE = dt.date.today().strftime("%Y%m%d")

INITIAL_CASH = 100_000.0
TARGET_PCT = 0.95
LOT_SIZE = 100  # [akquant] run_backtest(lot_size=) A 股最小交易单位
COMMISSION_RATE = 0.0000854  # [akquant] run_backtest(commission_rate=) 万 0.854
STAMP_TAX_RATE = 0.001  # [akquant] run_backtest(stamp_tax_rate=) 卖出印花税
# 相对开盘 ±2.5 个点；滑点 0.1%
ENTRY_PCT = 0.025
STOP_PCT = 0.025
# 前一日小阳线：相对开盘涨幅须低于此阈值（2.5 个点）
PREV_SMALL_YANG_PCT = 0.025
TICK_SIZE = 0.01  # A 股最小变动价位
SLIPPAGE = {"type": "percent", "value": 0.001}  # [akquant] 仅 run_backtest(slippage=)

FILL_CLOSE = CurrentClose()  # [akquant] 当根 K 线周期撮合；限价单触价成交见模块说明
REPORT_PATH = Path(__file__).with_name("kskj600552_report.html")


def ceil_to_tick(px: float, tick: float = TICK_SIZE) -> float:
    """向上取整到 tick（买入触发：至少达到 +pct）。"""
    if tick <= 0:
        return float(px)
    decimals = max(0, -int(round(math.log10(tick)))) if tick < 1 else 0
    return round(math.ceil((float(px) - 1e-12) / tick) * tick, decimals)


def floor_to_tick(px: float, tick: float = TICK_SIZE) -> float:
    """向下取整到 tick（止损触发：至少达到 −pct）。"""
    if tick <= 0:
        return float(px)
    decimals = max(0, -int(round(math.log10(tick)))) if tick < 1 else 0
    return round(math.floor((float(px) + 1e-12) / tick) * tick, decimals)


def entry_trigger_price(open_px: float) -> float:
    """买入触发价：开盘价 +2.5%，向上取整到 tick。"""
    return ceil_to_tick(float(open_px) * (1.0 + ENTRY_PCT))


def stop_trigger_price(open_px: float) -> float:
    """止损触发价：开盘价 −2.5%，向下取整到 tick。"""
    return floor_to_tick(float(open_px) * (1.0 - STOP_PCT))


def fetch_daily(symbol: str, start: str, end: str) -> pd.DataFrame:
    """前复权日线，清洗为 akquant 标准列；时间戳落到当日 15:00。

    输出列 date/open/high/low/close/volume/symbol 供 run_backtest(data=) 使用。
    """
    raw = ak.stock_zh_a_daily(
        symbol=symbol, start_date=start, end_date=end, adjust="qfq"
    )
    if raw is None or raw.empty:
        raise RuntimeError(f"未获取到日线: {symbol} {start}~{end}")

    df = raw.copy()
    if "date" not in df.columns and "日期" in df.columns:
        df = df.rename(columns={"日期": "date"})
    df["date"] = pd.to_datetime(df["date"])
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    df["symbol"] = symbol
    df["date"] = df["date"].dt.normalize() + pd.Timedelta(hours=15)
    if df["date"].dt.tz is None:
        df["date"] = df["date"].dt.tz_localize("Asia/Shanghai")
    return df[["date", "open", "high", "low", "close", "volume", "symbol"]].reset_index(
        drop=True
    )


def is_yin(open_px: float, close_px: float) -> bool:
    """阴线：收盘 < 开盘（不含十字星）。"""
    return float(close_px) < float(open_px)


def is_yang(open_px: float, close_px: float) -> bool:
    """阳线：收盘 > 开盘。"""
    return float(close_px) > float(open_px)


def prev_day_allows_entry(prev_open: float, prev_close: float) -> bool:
    """前一日允许今日买入：阴线，或收盘严格低于 open×(1+2.5%)（价格比较，避免浮点误差）。"""
    if prev_open <= 0:
        return False
    if prev_close <= prev_open:
        return True
    limit_px = prev_open * (1.0 + PREV_SMALL_YANG_PCT)
    return float(prev_close) < limit_px - 1e-8


def has_double_yang_before(
    prev2_open: float | None,
    prev2_close: float | None,
    prev_open: float | None,
    prev_close: float | None,
) -> bool:
    """前二日与前一日均为阳线 → 前面双阳，禁止买入。"""
    if None in (prev2_open, prev2_close, prev_open, prev_close):
        return False
    if prev2_open <= 0 or prev_open <= 0:
        return False
    return is_yang(prev2_open, prev2_close) and is_yang(prev_open, prev_close)


class OpenBreak3Strategy(Strategy):
    """相对开盘：+2.5%买入；-2.5%止损或阴线收盘卖；阳线持有。

    [akquant] 继承 Strategy，由引擎在每个 bar 上调用 on_bar。
    """

    def on_start(self) -> None:
        self.subscribe(SYMBOL)  # [akquant] 订阅标的行情
        self.lot_size = LOT_SIZE  # [akquant] 策略内下单手数提示（与 run_backtest lot_size 一致）
        self.armed = True
        self.entry_price: float | None = None
        self.prev_open: float | None = None
        self.prev_close: float | None = None
        self.prev2_open: float | None = None
        self.prev2_close: float | None = None
        self.buy_day: str | None = None  # 买入当日不再执行卖出判断
        self.log(
            f"{SYMBOL_NAME}({SYMBOL}) 开盘±{ENTRY_PCT*100:.1f}% "
            f"(+买/-止损，阴线收盘出，阳线持有) | "
            f"前日须阴线或小阳(<{PREV_SMALL_YANG_PCT*100:.1f}%)，禁前面双阳 | "
            f"佣金万0.854 滑点{SLIPPAGE['value']*100:.1f}% | {START_DATE}~{END_DATE}"
        )

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

    def _sync_position_state(self) -> float:
        """每根 K 线开头按实际持仓同步 armed（委托是否成交在 bar 结束后才入账）。"""
        pos = float(self.get_position(SYMBOL))
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
            self.sell(  # [akquant] 卖出；数量用 avail（T+1 可卖量）
                SYMBOL,
                avail,
                price=price,
            )
            self.log(
                f"{day} {reason} qty={avail:.0f} 限价={price:.2f} {hold_txt}"
            )
            self.armed = True
            self.entry_price = None
            self.buy_day = None
            return True
        if pos > 0:
            # [akquant] T+1：当日买入 pos>0 但 avail=0
            self.log(
                f"{day} {reason} 跳过(T+1 买入日不可卖) avail=0 pos={pos:.0f} {hold_txt}"
            )
        return False

    def _roll_prev_bars(self, open_px: float, close_px: float) -> None:
        """滚动前二日 / 前一日 OHLC，供次日买入过滤。"""
        self.prev2_open = self.prev_open
        self.prev2_close = self.prev_close
        self.prev_open = open_px
        self.prev_close = close_px

    def on_bar(self, bar) -> None:
        # [akquant] 每个 bar 回调一次；bar 为引擎推送的 K 线对象
        if bar.symbol != SYMBOL:
            return

        o = float(bar.open)  # [akquant] Bar 字段
        h = float(bar.high)
        low = float(bar.low)
        c = float(bar.close)
        day = self.to_local_time(bar.timestamp).strftime("%Y-%m-%d")  # [akquant] 时区转换

        bought_today = False
        try:
            pos = self._sync_position_state()

            entry_px = entry_trigger_price(o)
            stop_px = stop_trigger_price(o)
            hit_entry = h + 1e-12 >= entry_px
            hit_stop = low <= stop_px + 1e-12
            yin = is_yin(o, c)
            yang = is_yang(o, c)

            # 1) 空仓可买：最高价触及触发价，且前日形态符合
            if self.armed and pos <= 0 and hit_entry:
                can_buy = (
                    self.prev_open is not None
                    and self.prev_close is not None
                    and prev_day_allows_entry(self.prev_open, self.prev_close)
                    and not has_double_yang_before(
                        self.prev2_open,
                        self.prev2_close,
                        self.prev_open,
                        self.prev_close,
                    )
                )
                if can_buy:
                    self.order_target_percent(
                        symbol=SYMBOL,
                        target_percent=TARGET_PCT,
                        price=entry_px,
                    )
                    self.armed = False
                    self.entry_price = entry_px
                    self.buy_day = day
                    bought_today = True
                    self.log(
                        f"{day} 开盘+{ENTRY_PCT*100:.1f}%买入 限价={entry_px:.2f} "
                        f"(open={o:.2f} high={h:.2f}) 持有收益=+0.00%"
                    )
                elif self.prev_open is not None and self.prev_close is not None:
                    if not prev_day_allows_entry(self.prev_open, self.prev_close):
                        self.log(
                            f"{day} 触及买点但前日不符(须阴线或小阳"
                            f"<{PREV_SMALL_YANG_PCT*100:.1f}%) skip"
                        )
                    elif has_double_yang_before(
                        self.prev2_open,
                        self.prev2_close,
                        self.prev_open,
                        self.prev_close,
                    ):
                        self.log(f"{day} 触及买点但前面双阳 skip")

            # 2) 有仓卖出：买入当日跳过；止损优先，其次阴线收盘出
            if bought_today or self.buy_day == day:
                return

            pos = float(self.get_position(SYMBOL))  # [akquant]
            avail = float(self.get_available_position(SYMBOL))  # [akquant] T+1 可卖数量
            if pos <= 0 and avail <= 0:
                return

            if hit_stop:
                self._exit_all(
                    day=day,
                    avail=avail,
                    pos=pos,
                    price=stop_px,
                    reason=f"开盘-{STOP_PCT*100:.1f}%止损(open={o:.2f} low={low:.2f})",
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
                return

            if yang:
                # 阳线持有；十字星 c==o 亦不在此分支，默认持有
                pass
        finally:
            self._roll_prev_bars(o, c)


def _metric(metrics_df: pd.DataFrame, name: str) -> float:
    if name not in metrics_df.index:
        return float("nan")
    return float(metrics_df.loc[name, "value"])


def print_summary(result: aq.BacktestResult, data: pd.DataFrame) -> None:
    # [akquant] BacktestResult：metrics_df / executions_df / equity_curve_daily 等
    m = result.metrics_df  # [akquant] 绩效指标表
    c0 = float(data.iloc[0]["close"])
    c1 = float(data.iloc[-1]["close"])
    bh_pct = (c1 / c0 - 1.0) * 100.0

    print("\n========== 回测摘要 ==========")
    print(f"标的: {SYMBOL_NAME} ({SYMBOL})")
    print(f"区间: {data['date'].iloc[0]} → {data['date'].iloc[-1]}")
    print(f"日线根数: {len(data)}")
    print(f"买入: high>=ceil(open×{1+ENTRY_PCT:.3f})，止损 low<=floor(open×{1-STOP_PCT:.3f})")
    print(
        f"      前日须阴线或收盘严格<open×{1+PREV_SMALL_YANG_PCT:.3f}，禁前面双阳"
    )
    print(
        f"卖出: ①止损@触发价；②阴线@收盘；阳/十字持有；买入日不卖"
    )
    print(f"佣金: 万0.854 ({COMMISSION_RATE})；印花税(卖): {STAMP_TAX_RATE*100:.1f}%")
    print(f"滑点: {SLIPPAGE['value']*100:.1f}%")
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
    eq = result.equity_curve_daily  # [akquant] 日权益曲线
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

    exec_df = result.executions_df  # [akquant] 逐笔成交
    trades_df = result.trades_df if hasattr(result, "trades_df") else pd.DataFrame()  # [akquant] 闭环交易

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
        base_eq = float(prev.iloc[-1]) if not prev.empty else INITIAL_CASH
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
    print("说明: 策略收益%=该年末权益/上年年末权益-1；首年相对 INITIAL_CASH。")
    print("     买入持有%=该年末收盘/上年年末收盘-1（首年用当年首收）。")

def main() -> None:
    print(f"akquant={getattr(aq, '__version__', '?')}")
    print(f"拉取 {SYMBOL_NAME}({SYMBOL}) 日线 {START_DATE} → {END_DATE} ...")
    daily = fetch_daily(SYMBOL, START_DATE, END_DATE)
    print(
        f"日线数: {len(daily)}，"
        f"区间: {daily['date'].iloc[0]} → {daily['date'].iloc[-1]}"
    )

    result = aq.run_backtest(  # [akquant] 回测主入口
        data=daily,
        strategy=OpenBreak3Strategy,
        symbols=SYMBOL,
        initial_cash=INITIAL_CASH,
        commission_rate=COMMISSION_RATE,  # [akquant] 佣金率
        stamp_tax_rate=STAMP_TAX_RATE,  # [akquant] 卖出印花税
        t_plus_one=True,  # [akquant] A 股 T+1：当日买入不可卖，get_available_position=0
        lot_size=LOT_SIZE,  # [akquant] 100 股整数倍
        fill_policy=FILL_CLOSE,  # [akquant] 当根 K 线撮合；限价单见模块说明
        slippage=SLIPPAGE,  # [akquant] 全局滑点（订单层不再重复）
        timezone="Asia/Shanghai",  # [akquant] bar 与日志时区
        show_progress=False,
    )

    print("\n=== Backtest Result ===")
    print(result)
    print_summary(result, daily)

    print(f"\n生成 HTML: {REPORT_PATH}")
    result.viz.report(  # [akquant] 生成交互式 HTML 回测报告
        title=(
            f"{SYMBOL_NAME} 开盘±2.5%(阳持/阴出) "
            f"滑点0.1点 ({START_DATE}~{END_DATE})"
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
