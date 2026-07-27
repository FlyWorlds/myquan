"""非对称：开盘+4%买 / 开盘-3%止损或阴线收盘出。"""

from __future__ import annotations

import logging

import akquant as aq
from akquant import Strategy

from KSKJ600552 import (
    COMMISSION_RATE,
    END_DATE,
    FILL_CLOSE,
    INITIAL_CASH,
    LOT_SIZE,
    SLIPPAGE,
    START_DATE,
    STAMP_TAX_RATE,
    SYMBOL,
    SYMBOL_NAME,
    TARGET_PCT,
    fetch_daily,
)

logging.disable(logging.CRITICAL)

ENTRY_PCT = 0.04
STOP_PCT = 0.03


class AsymStrategy(Strategy):
    def on_start(self) -> None:
        self.subscribe(SYMBOL)
        self.lot_size = LOT_SIZE
        self.armed = True

    def on_bar(self, bar) -> None:
        if bar.symbol != SYMBOL:
            return
        o = float(bar.open)
        h = float(bar.high)
        low = float(bar.low)
        c = float(bar.close)
        pos = float(self.get_position(SYMBOL))
        entry_px = round(o * (1.0 + ENTRY_PCT), 2)
        stop_px = round(o * (1.0 - STOP_PCT), 2)

        if self.armed and pos <= 0 and h + 1e-12 >= entry_px:
            self.order_target_percent(
                symbol=SYMBOL,
                target_percent=TARGET_PCT,
                price=entry_px,
                fill_mode=FILL_CLOSE,
                slippage=SLIPPAGE,
            )
            self.armed = False

        pos = float(self.get_position(SYMBOL))
        avail = float(self.get_available_position(SYMBOL))
        if pos <= 0 and avail <= 0:
            return
        if low - 1e-12 <= stop_px:
            if avail > 0:
                self.sell(
                    SYMBOL,
                    avail,
                    price=stop_px,
                    fill_mode=FILL_CLOSE,
                    slippage=SLIPPAGE,
                )
                self.armed = True
            return
        if c < o and avail > 0:
            self.sell(
                SYMBOL, avail, price=c, fill_mode=FILL_CLOSE, slippage=SLIPPAGE
            )
            self.armed = True


def _m(metrics, name: str) -> float:
    if name not in metrics.index:
        return float("nan")
    return float(metrics.loc[name, "value"])


def main() -> None:
    daily = fetch_daily(SYMBOL, START_DATE, END_DATE)
    c0 = float(daily.iloc[0]["close"])
    c1 = float(daily.iloc[-1]["close"])
    bh = (c1 / c0 - 1.0) * 100.0

    result = aq.run_backtest(
        data=daily,
        strategy=AsymStrategy,
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
    m = result.metrics_df
    print(f"{SYMBOL_NAME} 开盘+{ENTRY_PCT*100:.0f}%买 / -{STOP_PCT*100:.0f}%止损或阴线出")
    print(f"区间日线={len(daily)}  买入持有={bh:.2f}%")
    print(f"累计收益%={_m(m,'total_return_pct'):.2f}")
    print(f"最大回撤%={_m(m,'max_drawdown_pct'):.2f}")
    print(f"胜率%={_m(m,'win_rate'):.2f}")
    print(f"闭环笔数={_m(m,'closed_trade_count'):.0f}")
    print(f"夏普={_m(m,'sharpe_ratio'):.3f}")
    print(f"期末市值={_m(m,'end_market_value'):.0f}")
    # compare refs
    print("对照: 对称4点 +9.24% | 对称3点 +55.19% | 对称2.5点 +63.54%")


if __name__ == "__main__":
    main()
