"""对比：阴线卖出 @ 收盘价 vs @ open-2.5% 触发价."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import akquant as aq
import pandas as pd

_PATH = Path(__file__).with_name("kskj.py")
spec = importlib.util.spec_from_file_location("kskj", _PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class YinSellAtStopStrategy(m.OpenBreak3Strategy):
    """阴线也按 open-2.5% 触发价卖出（未触止损线的阴线日）。"""

    def on_start(self) -> None:
        super().on_start()
        self.log("变体: 阴线卖出限价=open-2.5%(非收盘价)")

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
                    price=stop_px,
                    reason=f"开盘-{m.STOP_PCT*100:.1f}%止损",
                )
                return

            if yin:
                self._exit_all(
                    day=day,
                    avail=avail,
                    pos=pos,
                    price=stop_px,
                    reason="阴线@open-2.5%卖出",
                )
        finally:
            self._roll_prev_bars(o, c)


def run(label: str, strategy_cls: type, start: str) -> dict:
    daily = m.fetch_daily(m.SYMBOL, start, m.END_DATE)
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
    return {
        "label": label,
        "end_eq": end,
        "ret%": ret,
        "dd%": dd,
        "trades": n,
        "win%": wr,
    }


def main() -> None:
    periods = [("20250101", "2025至今"), ("20150529", "2015至今")]
    variants = [
        ("阴线@收盘价", m.OpenBreak3Strategy),
        ("阴线@open-2.5%", YinSellAtStopStrategy),
    ]
    rows = []
    for start, pname in periods:
        for vname, cls in variants:
            d = run(vname, cls, start)
            d["period"] = pname
            rows.append(d)

    df = pd.DataFrame(rows)
    print("=" * 60)
    print(f"{m.SYMBOL_NAME}  阴线卖出成交价对比")
    print("=" * 60)
    for pname in df["period"].unique():
        sub = df[df["period"] == pname]
        print(f"\n--- {pname} ---")
        for _, r in sub.iterrows():
            print(
                f"{r['label']:16}  收益 {r['ret%']:+.2f}%  "
                f"回撤 {r['dd%']:.2f}%  闭环 {int(r['trades'])}  "
                f"胜率 {r['win%']:.1f}%  期末 {r['end_eq']:,.0f}"
            )
        if len(sub) == 2:
            a, b = sub.iloc[0], sub.iloc[1]
            print(f"差异(变体-原版): 收益 {b['ret%']-a['ret%']:+.2f}pp  期末 {b['end_eq']-a['end_eq']:+,.0f}")

    print("\n说明:")
    print("- 原版: 阴线且 low 未触止损 -> 按收盘价限价卖")
    print("- 变体: 阴线且 low 未触止损 -> 按 floor(open×0.975) 限价卖")
    print("- 若 low 已触止损，两版均走止损分支")
    print("- 变体对「小阴线、low 未打到 -2.5%」卖价更低(更悲观)")


if __name__ == "__main__":
    main()
