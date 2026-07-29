"""日线阴阳策略 — akquant Strategy。"""

from __future__ import annotations

from akquant import Strategy

from strategy.yin_yang.rules import bar_shape, is_yin, is_yang


class YinYangStrategy(Strategy):
    """收阳买、收阴卖；不依赖 open_break。"""

    symbol: str = "sh600552"
    symbol_name: str = ""
    target_pct: float = 0.95
    start_date: str = ""
    end_date: str = ""

    def on_start(self) -> None:
        self.subscribe(self.symbol)
        self.log(
            f"{self.symbol_name or self.symbol} 日线阴阳(阳买/阴卖) "
            f"仓位{self.target_pct*100:.0f}% | {self.start_date}~{self.end_date}"
        )

    def on_bar(self, bar) -> None:
        if bar.symbol != self.symbol:
            return

        o = float(bar.open)
        c = float(bar.close)
        day = self.to_local_time(bar.timestamp).strftime("%Y-%m-%d")
        pos = float(self.get_position(self.symbol))
        shape = bar_shape(o, c)

        if pos <= 0 and is_yang(o, c):
            self.order_target_percent(
                symbol=self.symbol,
                target_percent=self.target_pct,
                price=c,
            )
            self.log(f"{day} 阳线买入 shape={shape} close={c:.2f}")
            return

        if pos > 0 and is_yin(o, c):
            avail = float(self.get_available_position(self.symbol))
            if avail > 0:
                self.sell(self.symbol, avail, price=c)
                self.log(f"{day} 阴线卖出 shape={shape} close={c:.2f}")
