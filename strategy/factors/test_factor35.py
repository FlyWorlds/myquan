import unittest
from strategy.factors.factor35 import evaluate_cash_gate, factor35_signal, SPEC

class Factor35Tests(unittest.TestCase):
    def test_extreme_panic_triggers_hard_cash(self):
        # 即使均线还在上方，极端踩踏（站上20日线比例 < 12%）也会无条件空仓
        res = evaluate_cash_gate(
            close_price=100.0,
            ma20=98.0,
            ma60=95.0,
            market_breadth_ma20=0.08,
            current_cash_state=False
        )
        self.assertTrue(res["is_cash"])
        self.assertIn("极端恐慌硬熔断", res["reason"])

    def test_composite_trend_and_breadth_panic(self):
        # 跌破 MA60 且 广度 < 28%
        res = evaluate_cash_gate(
            close_price=90.0,
            ma20=92.0,
            ma60=95.0,
            market_breadth_ma20=0.25,
            current_cash_state=False
        )
        self.assertTrue(res["is_cash"])
        self.assertIn("指数破位MA60", res["reason"])

    def test_normal_healthy_market_stays_invested(self):
        # 正常市场状态
        res = evaluate_cash_gate(
            close_price=105.0,
            ma20=100.0,
            ma60=95.0,
            market_breadth_ma20=0.65,
            current_cash_state=False
        )
        self.assertFalse(res["is_cash"])

    def test_exit_cash_gate_requires_both_trend_and_breadth(self):
        # 处于空仓状态时，只有站上 MA20 且 广度 > 35% 才能解除
        res_fail1 = evaluate_cash_gate(
            close_price=96.0,
            ma20=95.0,
            ma60=98.0,
            market_breadth_ma20=0.28,  # 广度未恢复
            current_cash_state=True
        )
        self.assertTrue(res_fail1["is_cash"])

        res_ok = evaluate_cash_gate(
            close_price=97.0,
            ma20=95.0,
            ma60=98.0,
            market_breadth_ma20=0.38,  # 恢复
            current_cash_state=True
        )
        self.assertFalse(res_ok["is_cash"])
        self.assertIn("解除空仓", res_ok["reason"])

    def test_tiered_position_levels(self):
        # 验证四级阶梯档位输出
        # 1. 极端熔断 (Tier 1: 0%)
        t1 = evaluate_cash_gate(close_price=100.0, ma20=98.0, ma60=95.0, market_breadth_ma20=0.08)
        self.assertEqual(t1["tier"], 1)
        self.assertEqual(t1["position_ratio"], 0.0)

        # 2. 破位轻仓防守 (Tier 2: 30%)
        t2 = evaluate_cash_gate(close_price=90.0, ma20=92.0, ma60=95.0, market_breadth_ma20=0.25)
        self.assertEqual(t2["tier"], 2)
        self.assertEqual(t2["position_ratio"], 0.3)

        # 3. 减速控仓 (Tier 3: 60%)
        t3 = evaluate_cash_gate(close_price=96.0, ma20=98.0, ma60=92.0, market_breadth_ma20=0.45)
        self.assertEqual(t3["tier"], 3)
        self.assertEqual(t3["position_ratio"], 0.6)

        # 4. 全力进攻 (Tier 4: 100%)
        t4 = evaluate_cash_gate(close_price=105.0, ma20=100.0, ma60=95.0, market_breadth_ma20=0.65)
        self.assertEqual(t4["tier"], 4)
        self.assertEqual(t4["position_ratio"], 1.0)

    def test_spec_registration(self):
        self.assertEqual(SPEC.id, "factor35")
        self.assertTrue(SPEC.implemented)


if __name__ == "__main__":
    unittest.main()
