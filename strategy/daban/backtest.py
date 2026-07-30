"""打板战法 — akquant Strategy。"""

from __future__ import annotations

from akquant import Strategy

from strategy.daban.rules import (
    DEFAULT_GAP_DOWN_EXIT_PCT,
    DEFAULT_LIMIT_PCT,
    DEFAULT_SEAL_HIGH_TICKS,
    DEFAULT_TARGET_PCT,
    is_limit_up_close,
    is_sealed_limit_up,
    should_gap_down_exit,
)


class DaBanStrategy(Strategy):
    """涨停封板买；次日低开走 / 不连板收盘卖 / 连板持有。"""

    symbol: str = "sh600552"
    symbol_name: str = ""
    target_pct: float = DEFAULT_TARGET_PCT
    limit_pct: float = DEFAULT_LIMIT_PCT
    gap_down_exit_pct: float = DEFAULT_GAP_DOWN_EXIT_PCT
    seal_high_ticks: float = DEFAULT_SEAL_HIGH_TICKS
    start_date: str = ""
    end_date: str = ""

    def on_start(self) -> None:
        self.subscribe(self.symbol)
        self._prev_close: float | None = None
        self.log(
            f"{self.symbol_name or self.symbol} 打板战法 "
            f"涨停{self.limit_pct*100:.0f}% 封板买 低开{self.gap_down_exit_pct*100:.0f}%走 "
            f"不连板卖 | 仓位{self.target_pct*100:.0f}% | "
            f"{self.start_date}~{self.end_date}"
        )

    def on_bar(self, bar) -> None:
        if bar.symbol != self.symbol:
            return

        o = float(bar.open)
        h = float(bar.high)
        low = float(bar.low)
        c = float(bar.close)
        day = self.to_local_time(bar.timestamp).strftime("%Y-%m-%d")
        prev_c = self._prev_close

        if prev_c is not None and prev_c > 0:
            pos = float(self.get_position(self.symbol))
            avail = float(self.get_available_position(self.symbol))

            if avail > 0:
                if should_gap_down_exit(o, prev_c, gap_down_exit_pct=self.gap_down_exit_pct):
                    self.sell(self.symbol, avail, price=o)
                    self.log(f"{day} 低开≥{self.gap_down_exit_pct*100:.0f}% 开盘卖 open={o:.2f}")
                elif not is_limit_up_close(
                    c, prev_c, limit_pct=self.limit_pct
                ):
                    self.sell(self.symbol, avail, price=c)
                    self.log(f"{day} 不连板 收盘卖 close={c:.2f}")
                elif is_sealed_limit_up(
                    o, h, low, c, prev_c,
                    limit_pct=self.limit_pct,
                    seal_high_ticks=self.seal_high_ticks,
                ):
                    self.log(f"{day} 连板持有 close={c:.2f}")

            if pos <= 0 and is_sealed_limit_up(
                o, h, low, c, prev_c,
                limit_pct=self.limit_pct,
                seal_high_ticks=self.seal_high_ticks,
            ):
                self.order_target_percent(
                    symbol=self.symbol,
                    target_percent=self.target_pct,
                    price=c,
                )
                self.log(f"{day} 涨停封板买入 close={c:.2f}")

        self._prev_close = c
