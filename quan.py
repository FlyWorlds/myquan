import akquant as aq
import akshare as ak
from akquant import Strategy
import pandas as pd


# 获取数据
df = ak.stock_zh_a_daily(
    symbol="sh600000",
    start_date="20250430",
    end_date="20260503"
)


class MyStrategy(Strategy):
    def __init__(self):
        super().__init__()
        self.bars = []

        # 用于中枢
        self.window = 20

        # 是否出现过一买
        self.has_first_buy = False

    def on_bar(self, bar):
        self.bars.append(bar)

        if len(self.bars) < self.window:
            return

        current_pos = self.get_position(bar.symbol)

        closes = [b.close for b in self.bars]
        highs = [b.high for b in self.bars]
        lows = [b.low for b in self.bars]
        vols = [b.volume for b in self.bars]

        # =========================
        # 1. 中枢（20日区间）
        # =========================
        zg = max(highs[-self.window:])
        zd = min(lows[-self.window:])

        in_range = zd < bar.close < zg

        # =========================
        # 2. 背驰（简化版）
        # =========================
        def calc_momentum(arr):
            return arr[-1] - arr[-5]

        price_momentum = calc_momentum(closes)
        vol_momentum = calc_momentum(vols)

        # 背驰：涨幅下降 + 成交量下降
        bearish_divergence = (
            price_momentum < 0 and
            vol_momentum < 0
        )

        # =========================
        # 3. 一买（背驰止跌）
        # =========================
        bottom_signal = (
            bearish_divergence and
            bar.close > lows[-2]
        )

        if current_pos == 0 and bottom_signal:
            self.buy(symbol=bar.symbol, quantity=100)
            self.has_first_buy = True
            print(f"[{bar.timestamp_str}] 一买 Bottom Buy @ {bar.close:.2f}")
            return

        # =========================
        # 4. 二买（核心）
        # =========================
        pullback_ok = (
            self.has_first_buy and
            in_range and
            bar.close > zd   # 不破中枢下沿
        )

        breakout = (
            bar.close > max(highs[-5:]) and
            vols[-1] > sum(vols[-5:]) / 5
        )

        second_buy = pullback_ok and breakout

        if current_pos == 0 and second_buy:
            self.buy(symbol=bar.symbol, quantity=200)
            print(f"[{bar.timestamp_str}] 二买 Breakout Buy @ {bar.close:.2f}")
            return

        # =========================
        # 5. 卖出逻辑（背驰 + 破中枢）
        # =========================
        top_signal = (
            bar.close < lows[-5] or
            (not in_range and bar.close < zg)
        )

        if current_pos > 0 and top_signal:
            self.close_position(symbol=bar.symbol)
            print(f"[{bar.timestamp_str}] Sell Exit @ {bar.close:.2f}")


# 回测
result = aq.run_backtest(
    data=df,
    strategy=MyStrategy,
    initial_cash=100000.0,
    symbols="sh600000"
)

print("\n=== Backtest Result ===")
print(result)

# 基准
benchmark_returns = (
    df.set_index("date")["close"]
    .pct_change()
    .fillna(0.0)
    .rename("BENCH")
)

result.report(
    filename="chan_daily_strategy.html",
    show=False,
    benchmark=benchmark_returns,
)