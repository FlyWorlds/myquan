"""策略十二·情绪门控开盘突破（不联网）。"""

from __future__ import annotations

import unittest

from strategy.core.context import MarketContext
from strategy.core.strategy_registry import get_strategy_spec
from strategy.factors.factor18 import factor18_signal
from strategy.strategies.strategy12.decision import create_decision_engine
from strategy.strategies.strategy12.emotion_gate import panic_halt_by_date


class TestStrategy12EmotionGate(unittest.TestCase):
    def test_registered_combo(self) -> None:
        spec = get_strategy_spec("strategy12")
        self.assertEqual(spec.id, "strategy12")
        ids = [b.factor_id for b in spec.factor_bindings if b.enabled]
        self.assertEqual(ids, ["factor18", "factor1", "factor2"])
        self.assertFalse(spec.meta.get("web_hide"))

    def test_strategy9_hidden_on_web(self) -> None:
        spec = get_strategy_spec("strategy9")
        self.assertTrue(spec.meta.get("web_hide"))
        self.assertEqual(spec.meta.get("canonical_factor"), "factor18")

    def test_factor18_panic_signal(self) -> None:
        self.assertEqual(factor18_signal(ld_open=4)["ldPhase"], "panic")
        self.assertEqual(factor18_signal(ld_open=0)["ldPhase"], "calm")

    def test_decision_blocks_new_buy_on_panic(self) -> None:
        eng = create_decision_engine()
        ctx = MarketContext(
            open=10.0,
            high=10.5,
            low=9.8,
            close=10.4,
            prev_open=10.2,
            prev_close=10.0,
            position_qty=0,
            meta={"ldPhase": "panic"},
        )
        d = eng.decide(ctx)
        self.assertEqual(d.action, "hold")
        self.assertIn("恐慌", d.reason)

    def test_decision_still_stops_in_panic(self) -> None:
        eng = create_decision_engine()
        ctx = MarketContext(
            open=10.0,
            high=10.1,
            low=9.6,
            close=9.7,
            prev_open=10.2,
            prev_close=10.0,
            position_qty=100,
            available_qty=100,
            buy_time="2020-01-02",
            session="2020-01-03",
            meta={"ldPhase": "panic", "t_plus_one": False},
        )
        d = eng.decide(ctx)
        self.assertEqual(d.action, "sell")

    def test_panic_halt_map_has_known_day(self) -> None:
        halt = panic_halt_by_date()
        self.assertTrue(halt)
        self.assertTrue(halt.get("2020-02-03"))


if __name__ == "__main__":
    unittest.main()
