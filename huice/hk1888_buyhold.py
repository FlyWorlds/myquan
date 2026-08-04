"""港股 HK1888 买入持有回测（同佣金/滑点/本金，便于与因子1对比）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import akquant as aq
from akquant import CurrentClose, Strategy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy.backtest import metric, print_monthly, print_yearly
from strategy.config import HK1888
from strategy.data import fetch_daily

CFG = HK1888


class BuyHoldStrategy(Strategy):
    symbol = CFG.symbol
    target_pct = CFG.target_pct
    bought = False

    def on_bar(self, bar):
        if BuyHoldStrategy.bought:
            return
        if str(bar.symbol) != self.symbol:
            return
        self.order_target_percent(
            symbol=self.symbol,
            target_percent=self.target_pct,
        )
        BuyHoldStrategy.bought = True


def main(*, show_report: bool = True) -> None:
    BuyHoldStrategy.bought = False
    print(f"akquant={getattr(aq, '__version__', '?')}")
    print(
        f"拉取 {CFG.symbol_name}({CFG.symbol}) 日线 "
        f"{CFG.start_date} → {CFG.end_date} ..."
    )
    daily = fetch_daily(CFG.symbol, CFG.start_date, CFG.end_date)
    print(
        f"日线数: {len(daily)}，"
        f"区间: {daily['date'].iloc[0]} → {daily['date'].iloc[-1]}"
    )

    result = aq.run_backtest(
        data=daily,
        strategy=BuyHoldStrategy,
        symbols=CFG.symbol,
        initial_cash=CFG.initial_cash,
        commission_rate=CFG.commission_rate,
        stamp_tax_rate=CFG.stamp_tax_rate,
        t_plus_one=True,
        lot_size=CFG.lot_size,
        fill_policy=CurrentClose(),
        slippage=CFG.slippage,
        timezone="Asia/Hong_Kong",
        show_progress=False,
    )
    print(result)

    m = result.metrics_df
    c0 = float(daily["close"].iloc[0])
    c1 = float(daily["close"].iloc[-1])
    print("\n========== 买入持有回测摘要 ==========")
    print(f"标的: {CFG.symbol_name} ({CFG.symbol})")
    print(
        f"规则: 首根日线按 {CFG.target_pct:.0%} 资金买入，持有至结束；"
        f"佣金万{CFG.commission_rate * 1e4:.3f}；"
        f"印花税(卖){CFG.stamp_tax_rate * 100:.1f}%；"
        f"滑点{CFG.slippage_value * 100:.1f}%"
    )
    print(f"总盈亏: {metric(m, 'total_pnl'):.2f}")
    print(f"累计收益%: {metric(m, 'total_return_pct'):.4f}")
    print(f"最大回撤%: {metric(m, 'max_drawdown_pct'):.4f}")
    print(f"夏普: {metric(m, 'sharpe_ratio'):.4f}")
    print(f"期末市值: {metric(m, 'end_market_value'):.2f}")
    print(f"价格涨幅(首收→末收): {(c1 / c0 - 1) * 100:.2f}%  ({c0:.2f} → {c1:.2f})")
    print_yearly(result, daily, initial_cash=CFG.initial_cash)
    print_monthly(result, daily, initial_cash=CFG.initial_cash)

    if not result.executions_df.empty:
        print("\n--- 成交明细 ---")
        cols = [
            c
            for c in ("symbol", "side", "quantity", "price", "commission", "timestamp")
            if c in result.executions_df.columns
        ]
        print(result.executions_df[cols].to_string(index=False))

    report = Path(__file__).with_name(f"{CFG.symbol_name}_买入持有_report.html")
    print(f"\n生成 HTML: {report}")
    result.viz.report(filename=str(report), show=show_report)
    print(f"报告: {report}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HK1888 买入持有回测")
    parser.add_argument("--no-open", action="store_true", help="不自动打开 HTML")
    args = parser.parse_args()
    main(show_report=not args.no_open)
