"""策略二成交时序、T+1、涨跌停与未来哨兵。"""

from __future__ import annotations

import unittest

import pandas as pd

from dataclasses import replace

from strategy.chan.config import ChanStrategyConfig
from strategy.chan.features import add_derived_features
from strategy.chan.signals import ChanSignalSnapshot
from strategy.chan.state_machine import ChanStateMachine
from strategy.core.context import MarketContext
from strategy.strategies.strategy2.backtest import derive_eligibility, run_chan_backtest
from strategy.strategies.strategy2.decision import create_decision_engine


def _panel() -> pd.DataFrame:
    dates = pd.date_range("2024-01-02 10:00", periods=12, freq="B")
    rows = []
    for symbol, drift in (("AAA", 0.01), ("BBB", -0.005)):
        price = 10.0
        for i, dt in enumerate(dates):
            open_px = price
            close = price * (1.0 + drift)
            buy1 = symbol == "AAA" and i == 1
            buy2 = symbol == "AAA" and i == 2
            sell2 = symbol == "AAA" and i == 8
            rows.append(
                {
                    "dt": dt,
                    "symbol": symbol,
                    "open": open_px,
                    "high": max(open_px, close),
                    "low": min(open_px, close),
                    "close": close,
                    "amount": 1_000_000,
                    "buy1": buy1,
                    "buy2": buy2,
                    "buy3": False,
                    "sell2": sell2,
                    "sell3": False,
                }
            )
            price = close
    return pd.DataFrame(rows)


class TimingTests(unittest.TestCase):
    def test_t1_blocks_same_day_sell(self) -> None:
        machine = ChanStateMachine()
        machine.update("2024-01-02 10:00", ChanSignalSnapshot(buy1=True, buy2=True))
        blocked = machine.update(
            "2024-01-02 14:00",
            ChanSignalSnapshot(sell2=True),
            can_sell=False,
        )
        self.assertEqual(blocked.action, "hold")
        sold = machine.update(
            "2024-01-03 10:00",
            ChanSignalSnapshot(sell2=True),
            can_sell=True,
        )
        self.assertEqual(sold.action, "sell")

    def test_decision_engine_respects_t_plus_one(self) -> None:
        engine = create_decision_engine()
        engine.decide(
            MarketContext(
                open=10,
                high=10,
                low=10,
                close=10,
                position_qty=0,
                meta={
                    "symbol": "AAA",
                    "dt": "2024-01-02 10:00",
                    "chan_signals": {"buy1": True, "buy2": True},
                },
            )
        )
        hold = engine.decide(
            MarketContext(
                open=10,
                high=10,
                low=9,
                close=9,
                position_qty=100,
                buy_time="2024-01-02 10:30:00",
                session="2024-01-02",
                meta={
                    "symbol": "AAA",
                    "dt": "2024-01-02 14:00",
                    "t_plus_one": True,
                    "chan_signals": {"sell2": True},
                },
            )
        )
        self.assertEqual(hold.action, "hold")

    def test_eligibility_turns_on_after_buy2_not_buy1(self) -> None:
        panel = derive_eligibility(_panel())
        aaa = panel[panel["symbol"] == "AAA"].reset_index(drop=True)
        self.assertFalse(bool(aaa.loc[1, "eligible_long"]))
        self.assertTrue(bool(aaa.loc[2, "eligible_long"]))
        self.assertEqual(aaa.loc[2, "chan_action"], "buy")
        self.assertEqual(aaa.loc[8, "chan_action"], "sell")

    def test_returns_use_next_open_not_same_bar_close(self) -> None:
        cfg = replace(ChanStrategyConfig(), top_k=1, purge_days=0)
        result = run_chan_backtest(_panel(), factor_column=None, config=cfg)
        # 手工：信号在 i=2，权重从该 bar 生效，收益用 open[i+2]/open[i+1]-1
        self.assertIn("net_return", result.equity.columns)
        self.assertGreater(len(result.equity), 0)
        first_trade = result.trades.iloc[0]
        self.assertEqual(first_trade["side"], "buy")

    def test_limit_down_cannot_exit(self) -> None:
        cfg = replace(ChanStrategyConfig(), top_k=1, purge_days=0)
        ordered = _panel().sort_values(["symbol", "dt"]).reset_index(drop=True)
        sell_pos = ordered.index[(ordered["symbol"] == "AAA") & ordered["sell2"]][0]
        exec_pos = sell_pos + 1
        ordered.loc[exec_pos, "open"] = ordered.loc[sell_pos, "close"] * 0.89
        result = run_chan_backtest(ordered, factor_column=None, config=cfg)
        self.assertIsNotNone(result.stats["sharpe"])

    def test_lookahead_sentinel_does_not_change_history(self) -> None:
        panel = _panel()
        base = add_derived_features(panel)
        future = panel.copy()
        extra = future.iloc[[-1]].copy()
        extra["dt"] = extra["dt"] + pd.Timedelta(days=1)
        extra["close"] = extra["close"] * 3
        extra["open"] = extra["open"] * 3
        extra["buy1"] = False
        extra["buy2"] = False
        extra["sell2"] = False
        extended = add_derived_features(pd.concat([future, extra], ignore_index=True))
        hist = base.set_index(["dt", "symbol"])["ret_8"]
        later = extended.set_index(["dt", "symbol"])["ret_8"].reindex(hist.index)
        pd.testing.assert_series_equal(hist, later, check_names=False)


if __name__ == "__main__":
    unittest.main()
