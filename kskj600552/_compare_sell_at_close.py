"""对比：止损 @ 触发价 vs 卖出统一 @ 收盘价（2025 起）."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import akquant as aq
import pandas as pd

_PATH = Path(__file__).with_name("kskj.py")
spec = importlib.util.spec_from_file_location("kskj", _PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class SellAllAtCloseStrategy(m.OpenBreak3Strategy):
    """触发条件不变；止损也按收盘价限价卖（与阴线同一时间节点）。"""

    def on_start(self) -> None:
        super().on_start()
        self.log("变体: 止损触发后亦按收盘价卖出")

    def on_bar(self, bar) -> None:
        if bar.symbol != m.SYMBOL:
            return

        o = float(bar.open)
        h = float(bar.high)
        low = float(bar.low)
        c = float(bar.close)
        day = self.to_local_time(bar.timestamp).strftime("%Y-%m-%d")

        bought_today = False
        try:
            pos = self._sync_position_state()
            entry_px = m.entry_trigger_price(o)
            stop_px = m.stop_trigger_price(o)
            hit_entry = h + 1e-12 >= entry_px
            hit_stop = low <= stop_px + 1e-12
            yin = m.is_yin(o, c)

            if self.armed and pos <= 0 and hit_entry:
                can_buy = (
                    self.prev_open is not None
                    and self.prev_close is not None
                    and m.prev_day_allows_entry(self.prev_open, self.prev_close)
                    and not m.has_double_yang_before(
                        self.prev2_open,
                        self.prev2_close,
                        self.prev_open,
                        self.prev_close,
                    )
                )
                if can_buy:
                    self.order_target_percent(
                        symbol=m.SYMBOL, target_percent=m.TARGET_PCT, price=entry_px
                    )
                    self.armed = False
                    self.entry_price = entry_px
                    self.buy_day = day
                    bought_today = True

            if bought_today or self.buy_day == day:
                return

            pos = float(self.get_position(m.SYMBOL))
            avail = float(self.get_available_position(m.SYMBOL))
            if pos <= 0 and avail <= 0:
                return

            if hit_stop:
                self._exit_all(
                    day=day,
                    avail=avail,
                    pos=pos,
                    price=float(c),
                    reason=f"触止损但收盘卖(open={o:.2f} low={low:.2f} close={c:.2f})",
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


class CloseTriggerSellStrategy(m.OpenBreak3Strategy):
    """触发与成交均在收盘：close<=止损线 或 阴线 → 收盘价卖。"""

    def on_start(self) -> None:
        super().on_start()
        self.log("变体: 止损/阴线均仅在收盘判断，收盘价卖出")

    def on_bar(self, bar) -> None:
        if bar.symbol != m.SYMBOL:
            return

        o = float(bar.open)
        h = float(bar.high)
        low = float(bar.low)
        c = float(bar.close)
        day = self.to_local_time(bar.timestamp).strftime("%Y-%m-%d")

        bought_today = False
        try:
            pos = self._sync_position_state()
            entry_px = m.entry_trigger_price(o)
            stop_px = m.stop_trigger_price(o)
            hit_entry = h + 1e-12 >= entry_px
            close_stop = c <= stop_px + 1e-12
            yin = m.is_yin(o, c)

            if self.armed and pos <= 0 and hit_entry:
                can_buy = (
                    self.prev_open is not None
                    and self.prev_close is not None
                    and m.prev_day_allows_entry(self.prev_open, self.prev_close)
                    and not m.has_double_yang_before(
                        self.prev2_open,
                        self.prev2_close,
                        self.prev_open,
                        self.prev_close,
                    )
                )
                if can_buy:
                    self.order_target_percent(
                        symbol=m.SYMBOL, target_percent=m.TARGET_PCT, price=entry_px
                    )
                    self.armed = False
                    self.entry_price = entry_px
                    self.buy_day = day
                    bought_today = True

            if bought_today or self.buy_day == day:
                return

            pos = float(self.get_position(m.SYMBOL))
            avail = float(self.get_available_position(m.SYMBOL))
            if pos <= 0 and avail <= 0:
                return

            if close_stop:
                self._exit_all(
                    day=day,
                    avail=avail,
                    pos=pos,
                    price=float(c),
                    reason=f"收盘<=止损线收盘卖(close={c:.2f} stop={stop_px:.2f})",
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


def run(label: str, strategy_cls: type) -> dict:
    daily = m.fetch_daily(m.SYMBOL, m.START_DATE, m.END_DATE)
    r = aq.run_backtest(
        data=daily,
        strategy=strategy_cls,
        symbols=m.SYMBOL,
        initial_cash=m.INITIAL_CASH,
        commission_rate=m.COMMISSION_RATE,
        stamp_tax_rate=m.STAMP_TAX_RATE,
        t_plus_one=True,
        lot_size=m.LOT_SIZE,
        fill_policy=m.FILL_CLOSE,
        slippage=m.SLIPPAGE,
        timezone="Asia/Shanghai",
        show_progress=False,
    )
    met = r.metrics_df
    end = float(r.equity_curve_daily.iloc[-1])
    ret = (end / m.INITIAL_CASH - 1) * 100
    dd = float(met.loc["max_drawdown_pct", "value"]) if "max_drawdown_pct" in met.index else float("nan")
    n = int(met.loc["closed_trade_count", "value"]) if "closed_trade_count" in met.index else 0
    wr = float(met.loc["win_rate", "value"]) if "win_rate" in met.index else float("nan")
    return {"label": label, "end_eq": end, "ret%": ret, "dd%": dd, "trades": n, "win%": wr}


def main() -> None:
    variants = [
        ("原版: 止损@触发价/阴线@收盘", m.OpenBreak3Strategy),
        ("变体A: low触止损但@收盘卖", SellAllAtCloseStrategy),
        ("变体B: 收盘<=止损线才卖", CloseTriggerSellStrategy),
    ]
    rows = [run(l, c) for l, c in variants]
    df = pd.DataFrame(rows)
    print("=" * 62)
    print(f"{m.SYMBOL_NAME}  卖出时间节点/成交价对比  ({m.START_DATE}~{m.END_DATE})")
    print("=" * 62)
    for _, r in df.iterrows():
        print(
            f"{r['label']:28}  收益 {r['ret%']:+.2f}%  "
            f"回撤 {r['dd%']:.2f}%  闭环 {int(r['trades'])}  "
            f"胜率 {r['win%']:.1f}%  期末 {r['end_eq']:,.0f}"
        )
    base = df.iloc[0]
    for _, r in df.iloc[1:].iterrows():
        print(
            f"  vs 原版: 收益 {r['ret%']-base['ret%']:+.2f}pp  "
            f"期末 {r['end_eq']-base['end_eq']:+,.0f}"
        )


if __name__ == "__main__":
    main()
