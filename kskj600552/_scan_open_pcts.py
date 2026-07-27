"""对比相对开盘 ±3 / ±2.5 / ±2 三个幅度（同一策略、滑点0.1点）。"""

from __future__ import annotations

import logging
from typing import Any

import akquant as aq
import pandas as pd
from akquant import CurrentClose, Strategy

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

PCTS = (0.04, 0.03, 0.025, 0.02)


class OpenBreakParamStrategy(Strategy):
    """相对开盘 ±pct：冲高买、对称止损、阴线收盘出、阳线持有。"""

    def __init__(self, entry_pct: float = 0.025, **kwargs: Any) -> None:
        super().__init__()
        self.entry_pct = float(entry_pct)
        self.stop_pct = float(entry_pct)

    def on_start(self) -> None:
        self.subscribe(SYMBOL)
        self.lot_size = LOT_SIZE
        self.armed = True

    def _exit_all(self, avail: float, pos: float, price: float) -> None:
        if avail > 0:
            self.sell(
                SYMBOL,
                avail,
                price=price,
                fill_mode=FILL_CLOSE,
                slippage=SLIPPAGE,
            )
            self.armed = True

    def on_bar(self, bar) -> None:
        if bar.symbol != SYMBOL:
            return
        o, h, low, c = float(bar.open), float(bar.high), float(bar.low), float(bar.close)
        pos = float(self.get_position(SYMBOL))
        entry_px = round(o * (1.0 + self.entry_pct), 2)
        stop_px = round(o * (1.0 - self.stop_pct), 2)
        hit_entry = h + 1e-12 >= entry_px
        hit_stop = low - 1e-12 <= stop_px
        yin = c < o

        if self.armed and pos <= 0 and hit_entry:
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
        if hit_stop:
            self._exit_all(avail, pos, stop_px)
            return
        if yin:
            self._exit_all(avail, pos, c)


def _m(metrics: pd.DataFrame, name: str) -> float:
    if name not in metrics.index:
        return float("nan")
    return float(metrics.loc[name, "value"])


def main() -> None:
    daily = fetch_daily(SYMBOL, START_DATE, END_DATE)
    c0, c1 = float(daily.iloc[0]["close"]), float(daily.iloc[-1]["close"])
    bh = (c1 / c0 - 1.0) * 100.0

    # 信号日统计（无状态机，仅看触及次数）
    rows = []
    for pct in PCTS:
        hit_up = (daily["high"] >= (daily["open"] * (1 + pct)).round(2)).sum()
        hit_dn = (daily["low"] <= (daily["open"] * (1 - pct)).round(2)).sum()
        result = aq.run_backtest(
            data=daily,
            strategy=OpenBreakParamStrategy(entry_pct=pct),
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
        rows.append(
            {
                "幅度(点)": f"{pct*100:.1f}",
                "累计收益%": round(_m(m, "total_return_pct"), 2),
                "最大回撤%": round(_m(m, "max_drawdown_pct"), 2),
                "胜率%": round(_m(m, "win_rate"), 2),
                "闭环笔数": int(_m(m, "closed_trade_count")),
                "夏普": round(_m(m, "sharpe_ratio"), 3),
                "期末市值": round(_m(m, "end_market_value"), 0),
                "触及+N天数": int(hit_up),
                "触及-N天数": int(hit_dn),
            }
        )

    out = pd.DataFrame(rows)
    print(f"{SYMBOL_NAME}({SYMBOL}) 较开盘对称幅度对比")
    print(f"区间: {daily['date'].iloc[0]} -> {daily['date'].iloc[-1]}  日线={len(daily)}")
    print(f"规则: 冲高+N买入 / -N止损 / 阴线收盘出 / 阳线持有 | 滑点0.1点")
    print(f"买入持有: {bh:.2f}%  ({c0:.2f} -> {c1:.2f})")
    print()
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
