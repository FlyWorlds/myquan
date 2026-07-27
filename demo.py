import akquant as aq
import akshare as ak
from akquant import Strategy

# 1. 准备数据
# 使用 akshare 获取 A 股历史数据 (需安装: pip install akshare)
df = ak.stock_zh_a_daily(symbol="sh600000", start_date="20250212", end_date="20260212")


class MyStrategy(Strategy):
    def on_bar(self, bar):
        # 简单策略示例:
        # 当收盘价 > 开盘价 (阳线) -> 买入
        # 当收盘价 < 开盘价 (阴线) -> 卖出

        # 获取当前持仓
        current_pos = self.get_position(bar.symbol)

        if current_pos == 0 and bar.close > bar.open:
            self.buy(symbol=bar.symbol, quantity=100)
            print(f"[{bar.timestamp_iso}] Buy 100 at {bar.close:.2f}")  # UTC ISO 8601

        elif current_pos > 0 and bar.close < bar.open:
            self.close_position(symbol=bar.symbol)
            print(f"[{bar.timestamp_iso}] Sell 100 at {bar.close:.2f}")  # UTC ISO 8601


# 运行回测
result = aq.run_backtest(
    data=df,
    strategy=MyStrategy,
    initial_cash=100000.0,
    symbols="sh600000"
)

# 打印回测结果
print("\n=== Backtest Result ===")
print(result)

# 生成最小基准对比报告
benchmark_returns = (
    df.set_index("date")["close"].pct_change().fillna(0.0).rename("SIMPLE_BENCH")
)
result.viz.report(
    filename="quickstart_report.html",
    show=False,
    benchmark=benchmark_returns,
)