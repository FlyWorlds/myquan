"""策略二缠论状态机、信号投影与 CZSC 参考一致性。"""

from __future__ import annotations

import unittest

import pandas as pd

from strategy.chan.data_adapter import synthetic_frame, to_raw_bars, validate_czsc_frame
from strategy.chan.signals import (
    ChanSignalSnapshot,
    generate_signal_frame,
    project_signal_columns,
)
from strategy.chan.state_machine import ChanState, ChanStateMachine
from strategy.core.context import MarketContext
from strategy.strategies.strategy2.decision import create_decision_engine


class ChanStateMachineTests(unittest.TestCase):
    def test_buy1_then_buy2_confirms_entry(self) -> None:
        machine = ChanStateMachine()
        first = machine.update("2024-01-02 10:00", ChanSignalSnapshot(buy1=True))
        self.assertEqual(first.action, "candidate")
        self.assertEqual(machine.state, ChanState.WAIT_BUY2)
        second = machine.update("2024-01-02 10:30", ChanSignalSnapshot(buy2=True))
        self.assertEqual(second.action, "buy")
        self.assertEqual(machine.state, ChanState.LONG)

    def test_buy2_alone_does_not_open(self) -> None:
        machine = ChanStateMachine()
        out = machine.update("2024-01-02 10:00", ChanSignalSnapshot(buy2=True))
        self.assertEqual(out.action, "hold")
        self.assertEqual(machine.state, ChanState.FLAT)

    def test_same_bar_buy1_and_buy2_confirms(self) -> None:
        machine = ChanStateMachine()
        out = machine.update(
            "2024-01-02 10:00", ChanSignalSnapshot(buy1=True, buy2=True)
        )
        self.assertEqual(out.action, "buy")

    def test_sell2_or_sell3_exits(self) -> None:
        machine = ChanStateMachine()
        machine.update("2024-01-02 10:00", ChanSignalSnapshot(buy1=True, buy2=True))
        sell2 = machine.update("2024-01-03 10:00", ChanSignalSnapshot(sell2=True))
        self.assertEqual(sell2.action, "sell")
        self.assertEqual(sell2.reason, "二卖退出")

        machine.update("2024-01-04 10:00", ChanSignalSnapshot(buy1=True, buy2=True))
        sell3 = machine.update("2024-01-05 10:00", ChanSignalSnapshot(sell3=True))
        self.assertEqual(sell3.reason, "三卖退出")

    def test_candidate_timeout(self) -> None:
        machine = ChanStateMachine(candidate_timeout_bars=2)
        machine.update("2024-01-02 10:00", ChanSignalSnapshot(buy1=True))
        machine.update("2024-01-02 10:30", ChanSignalSnapshot())
        timed_out = machine.update("2024-01-02 11:00", ChanSignalSnapshot())
        self.assertEqual(timed_out.reason, "一买候选超时")
        self.assertEqual(machine.state, ChanState.FLAT)

    def test_limit_up_blocks_new_entry(self) -> None:
        machine = ChanStateMachine()
        out = machine.update(
            "2024-01-02 10:00",
            ChanSignalSnapshot(buy1=True, buy2=True, limit_up=True),
        )
        self.assertEqual(out.action, "hold")
        self.assertEqual(machine.state, ChanState.FLAT)


class SignalProjectionTests(unittest.TestCase):
    def test_project_versioned_czsc_columns(self) -> None:
        frame = pd.DataFrame(
            {
                "30分钟_D1B_BUY1": ["一买_5笔_任意_0", "其他"],
                "30分钟_D1#SMA#21_BS2辅助V230320": ["二买_任意_任意_0", "二卖_任意_任意_0"],
                "日线_D1B_BUY1": ["其他", "一买_5笔_任意_0"],
                "日线_D1#SMA#21_BS2辅助V230320": ["二卖_任意_任意_0", "其他"],
                "日线_D1_三买辅助V230228": ["其他", "三买_6笔_任意_0"],
                "日线_D1#SMA#34_BS3辅助V230319": ["三卖_均线新低_任意_0", "其他"],
                "日线_D1_表里关系V230101": ["向下_任意_任意_0", "向上_任意_任意_0"],
            }
        )
        out = project_signal_columns(frame)
        self.assertTrue(bool(out.loc[0, "m30_buy1"]))
        self.assertTrue(bool(out.loc[0, "m30_buy2"]))
        self.assertTrue(bool(out.loc[1, "daily_buy3"]))
        self.assertTrue(bool(out.loc[0, "daily_sell3"]))
        self.assertTrue(bool(out.loc[0, "daily_sell2"]))
        self.assertTrue(bool(out.loc[0, "daily_bi_down"]))

    def test_xiaozhuan_requires_daily_down_context(self) -> None:
        from strategy.chan.signals import apply_xiaozhuan

        frame = pd.DataFrame(
            {
                "m30_buy1": [True, True],
                "m30_buy2": [False, True],
                "daily_bi_down": [False, True],
                "daily_buy1": [False, False],
                "daily_macd_bottom": [False, False],
                "daily_buy3": [False, False],
                "daily_sell2": [False, False],
                "daily_sell3": [False, False],
            }
        )
        out = apply_xiaozhuan(frame)
        self.assertFalse(bool(out.loc[0, "buy1"]))
        self.assertFalse(bool(out.loc[0, "buy2"]))
        self.assertTrue(bool(out.loc[1, "buy1"]))
        self.assertTrue(bool(out.loc[1, "buy2"]))

    def test_collapse_uses_intraday_buy_and_eod_daily_env(self) -> None:
        from strategy.chan.signals import collapse_signals_to_daily

        frame = pd.DataFrame(
            {
                "dt": pd.to_datetime(
                    [
                        "2024-01-02 10:00",
                        "2024-01-02 15:00",
                        "2024-01-03 10:00",
                    ]
                ),
                "symbol": ["AAA", "AAA", "AAA"],
                "m30_buy1": [True, False, False],
                "m30_buy2": [False, True, False],
                "daily_bi_down": [False, True, False],
                "daily_buy1": [False, False, False],
                "daily_macd_bottom": [False, False, False],
                "daily_buy3": [False, False, False],
                "daily_sell2": [False, False, True],
                "daily_sell3": [False, False, False],
                "daily_bi_up": [False, False, True],
                "daily_sell1": [False, False, False],
                "daily_buy2": [False, False, False],
                "daily_macd_top": [False, False, False],
            }
        )
        daily = collapse_signals_to_daily(frame)
        day1 = daily[daily["dt"] == pd.Timestamp("2024-01-02")].iloc[0]
        self.assertTrue(bool(day1["m30_buy1"]))
        self.assertTrue(bool(day1["m30_buy2"]))
        self.assertTrue(bool(day1["buy2"]))
        day2 = daily[daily["dt"] == pd.Timestamp("2024-01-03")].iloc[0]
        self.assertTrue(bool(day2["sell2"]))
        self.assertFalse(bool(day2["buy2"]))

    def test_czsc_signal_generation_is_deterministic(self) -> None:
        raw = synthetic_frame("AAA", start="20220101", end="20230101", seed=7)
        quality = validate_czsc_frame(raw, symbol="AAA", source="synthetic")
        self.assertTrue(quality.valid)
        bars = to_raw_bars(raw, freq="30分钟")
        first = generate_signal_frame(bars, init_n=80)
        second = generate_signal_frame(bars, init_n=80)
        cols = ["m30_buy1", "m30_buy2", "daily_sell2"]
        present = [c for c in cols if c in first.columns]
        pd.testing.assert_frame_equal(first[present], second[present])
        self.assertGreater(int(first["m30_buy1"].sum() + first["m30_buy2"].sum()), 0)


class DecisionEngineTests(unittest.TestCase):
    def test_decision_engine_follows_state_machine(self) -> None:
        engine = create_decision_engine()
        ctx1 = MarketContext(
            open=10,
            high=10.2,
            low=9.8,
            close=10.1,
            session="2024-01-02",
            meta={
                "symbol": "AAA",
                "dt": "2024-01-02 10:00",
                "chan_signals": {"buy1": True},
            },
        )
        self.assertEqual(engine.decide(ctx1).action, "hold")
        ctx2 = MarketContext(
            open=10.1,
            high=10.4,
            low=10.0,
            close=10.3,
            session="2024-01-02",
            meta={
                "symbol": "AAA",
                "dt": "2024-01-02 10:30",
                "chan_signals": {"buy2": True},
            },
        )
        self.assertEqual(engine.decide(ctx2).action, "buy")


if __name__ == "__main__":
    unittest.main()
