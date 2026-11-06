"""策略三十七与因子37（跌停开板缠论反转策略）单元测试。"""

from __future__ import annotations

import unittest
import pandas as pd
from czsc import CZSC, Direction, Freq, RawBar

from strategy.core.context import MarketContext
from strategy.factors.factor37 import (
    evaluate_limit_down_chan_signal,
    is_mainboard,
)
from strategy.registry import get_strategy
from strategy.strategies.strategy37.decision import Strategy37Decision


class TestStrategy37(unittest.TestCase):
    def test_mainboard_filter(self) -> None:
        self.assertTrue(is_mainboard("sh600000"))
        self.assertTrue(is_mainboard("sh601988"))
        self.assertTrue(is_mainboard("sz000001"))
        self.assertTrue(is_mainboard("sz002580"))
        # 排除创业板/科创板/北交所
        self.assertFalse(is_mainboard("sz300750"))
        self.assertFalse(is_mainboard("sh688981"))
        self.assertFalse(is_mainboard("bj830000"))

    def test_strategy_registration(self) -> None:
        entry = get_strategy("strategy37")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.id, "strategy37")
        self.assertIn("跌停开板", entry.name)
        self.assertIn("factor37", entry.factor_ids)
        # 测试别名
        alias_entry = get_strategy("跌停开板缠论")
        self.assertEqual(alias_entry.id, "strategy37")

    def test_decision_engine_holding_sell(self) -> None:
        engine = Strategy37Decision(holding_days=5)
        # 测试持仓达 5 天且 T+1 已解禁发出卖出决策
        ctx_sell = MarketContext(
            open=10.0,
            high=10.5,
            low=9.8,
            close=10.2,
            position_qty=1000.0,
            available_qty=1000.0,
            meta={"symbol": "sh600000", "held_days": 5, "t_plus_one": False},
        )
        dec_sell = engine.decide(ctx_sell)
        self.assertEqual(dec_sell.action, "sell")
        self.assertIn("d5", dec_sell.reason)

        # 测试持仓未达 5 天继续持有
        ctx_hold = MarketContext(
            open=10.0,
            high=10.5,
            low=9.8,
            close=10.2,
            position_qty=1000.0,
            available_qty=1000.0,
            meta={"symbol": "sh600000", "held_days": 2, "t_plus_one": False},
        )
        dec_hold = engine.decide(ctx_hold)
        self.assertEqual(dec_hold.action, "hold")


    def test_signal_evaluation_st_and_board_filter(self) -> None:
        # 非主板排除
        dummy_czsc = None  # type: ignore
        res_cyb = evaluate_limit_down_chan_signal(
            symbol="sz300750",
            prev_close=10.0,
            open_px=9.0,
            high_px=9.2,
            low_px=9.0,
            close_px=9.1,
            bar_dt=pd.Timestamp("2024-01-02"),
            czsc_engine=dummy_czsc,  # type: ignore
        )
        self.assertFalse(res_cyb["signal"])
        self.assertEqual(res_cyb["reason"], "非主板标的")

        # ST标的排除
        res_st = evaluate_limit_down_chan_signal(
            symbol="sh600000",
            prev_close=10.0,
            open_px=9.0,
            high_px=9.2,
            low_px=9.0,
            close_px=9.1,
            bar_dt=pd.Timestamp("2024-01-02"),
            czsc_engine=dummy_czsc,  # type: ignore
            is_st=True,
        )
        self.assertFalse(res_st["signal"])
        self.assertEqual(res_st["reason"], "ST标的剔除")


if __name__ == "__main__":
    unittest.main()
