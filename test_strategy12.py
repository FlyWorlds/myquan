"""策略十二·涨停次日低开（不联网）。"""

from __future__ import annotations

import unittest

from strategy.core.context import MarketContext
from strategy.core.strategy_registry import get_strategy_spec
from strategy.factors.factor18 import factor18_signal
from strategy.factors.factor21 import factor21_signal
from strategy.strategies.strategy12.decision import create_decision_engine


class TestStrategy12LimitUpNextGap(unittest.TestCase):
    def test_registered_combo(self) -> None:
        spec = get_strategy_spec("strategy12")
        self.assertEqual(spec.id, "strategy12")
        ids = [b.factor_id for b in spec.factor_bindings if b.enabled]
        self.assertEqual(ids, ["factor18", "factor21"])
        self.assertEqual(spec.meta.get("mode"), "lu_next_gap")
        self.assertEqual(spec.meta.get("validation"), "oos_failed")

    def test_factor18_panic_signal(self) -> None:
        self.assertEqual(factor18_signal(ld_open=4)["ldPhase"], "panic")

    def test_factor21_requires_yest_lu_and_gap(self) -> None:
        miss = factor21_signal(
            yest_close_limit_up=False,
            today_limit_up_open=False,
            ld_open=0,
            gap=-0.02,
            open_px=10.0,
        )
        self.assertFalse(miss["allow"])
        deep = factor21_signal(
            yest_close_limit_up=True,
            today_limit_up_open=False,
            ld_open=0,
            gap=-0.08,
            open_px=10.0,
        )
        self.assertFalse(deep["allow"])
        panic = factor21_signal(
            yest_close_limit_up=True,
            today_limit_up_open=False,
            ld_open=4,
            gap=-0.02,
            open_px=10.0,
        )
        self.assertFalse(panic["allow"])
        ok = factor21_signal(
            yest_close_limit_up=True,
            today_limit_up_open=False,
            ld_open=0,
            gap=-0.02,
            open_px=10.0,
        )
        self.assertTrue(ok["allow"])

    def test_decision_buys_on_lu_next_gap(self) -> None:
        eng = create_decision_engine()
        ctx = MarketContext(
            open=9.8,
            high=10.2,
            low=9.6,
            close=10.0,
            prev_close=10.0,
            position_qty=0,
            meta={
                "ld_open": 0,
                "yest_close_limit_up": True,
                "today_limit_up_open": False,
                "gap": -0.02,
            },
        )
        d = eng.decide(ctx)
        self.assertEqual(d.action, "buy")

    def test_decision_blocks_panic(self) -> None:
        eng = create_decision_engine()
        ctx = MarketContext(
            open=9.8,
            high=10.2,
            low=9.6,
            close=10.0,
            prev_close=10.0,
            position_qty=0,
            meta={
                "ld_open": 4,
                "yest_close_limit_up": True,
                "today_limit_up_open": False,
                "gap": -0.02,
            },
        )
        d = eng.decide(ctx)
        self.assertEqual(d.action, "hold")
        self.assertIn("恐慌", d.reason)

    def test_decision_flatten_t1(self) -> None:
        eng = create_decision_engine()
        ctx = MarketContext(
            open=10.0,
            high=10.1,
            low=9.6,
            close=9.7,
            prev_close=10.0,
            position_qty=100,
            available_qty=100,
            meta={"t_plus_one": False},
        )
        d = eng.decide(ctx)
        self.assertEqual(d.action, "sell")


if __name__ == "__main__":
    unittest.main()
