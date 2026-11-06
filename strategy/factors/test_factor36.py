import unittest
from strategy.factors.factor36 import evaluate_tech_cash_gate, factor36_signal, SPEC


class Factor36Tests(unittest.TestCase):
    def test_extreme_panic_triggers_hard_cash(self):
        # 即使创业板均线还在上方，极端踩踏（科技站上20日线比例 < 15%）也会触发硬熔断空仓
        res = evaluate_tech_cash_gate(
            cyb_close=2600.0,
            cyb_ma20=2550.0,
            cyb_ma60=2500.0,
            tech_breadth_ma20=0.10,
            current_cash_state=False,
        )
        self.assertTrue(res["is_cash"])
        self.assertIn("极端流动性熔断", res["reason"])

    def test_tech_macro_and_breadth_panic(self):
        # 创业板破位 MA60 且 科技广度 < 30%
        res = evaluate_tech_cash_gate(
            cyb_close=2400.0,
            cyb_ma20=2480.0,
            cyb_ma60=2550.0,
            sz_close=10000.0,
            sz_ma60=10500.0,
            tech_breadth_ma20=0.25,
            current_cash_state=False,
        )
        self.assertTrue(res["is_cash"])
        self.assertIn("失守MA60且科技广度溃败", res["reason"])

    def test_tech_normal_healthy_market_stays_invested(self):
        # 科技多头强势
        res = evaluate_tech_cash_gate(
            cyb_close=2700.0,
            cyb_ma20=2650.0,
            cyb_ma60=2500.0,
            sz_close=11500.0,
            sz_ma60=11000.0,
            tech_breadth_ma20=0.65,
            current_cash_state=False,
        )
        self.assertFalse(res["is_cash"])

    def test_tech_exit_requires_both_cyb_rebound_and_breadth(self):
        # 处于科技空仓时，只有创业板站上 MA20 且 科技广度 > 38% 才能解除
        res_fail1 = evaluate_tech_cash_gate(
            cyb_close=2500.0,
            cyb_ma20=2480.0,
            cyb_ma60=2550.0,
            tech_breadth_ma20=0.28,  # 广度未到 38%
            current_cash_state=True,
        )
        self.assertTrue(res_fail1["is_cash"])

        res_ok = evaluate_tech_cash_gate(
            cyb_close=2550.0,
            cyb_ma20=2500.0,
            cyb_ma60=2580.0,
            tech_breadth_ma20=0.42,  # 广度恢复
            current_cash_state=True,
        )
        self.assertFalse(res_ok["is_cash"])
        self.assertIn("解除空仓", res_ok["reason"])

    def test_tech_tiered_position_levels(self):
        # 1. 科技极端熔断 (Tier 1: 0%)
        t1 = evaluate_tech_cash_gate(cyb_close=2600.0, cyb_ma20=2550.0, cyb_ma60=2500.0, tech_breadth_ma20=0.10)
        self.assertEqual(t1["tier"], 1)
        self.assertEqual(t1["position_ratio"], 0.0)

        # 2. 科技轻仓防守 (Tier 2: 30%)
        t2 = evaluate_tech_cash_gate(cyb_close=2400.0, cyb_ma20=2480.0, cyb_ma60=2550.0, tech_breadth_ma20=0.25)
        self.assertEqual(t2["tier"], 2)
        self.assertEqual(t2["position_ratio"], 0.3)

        # 3. 科技减速控仓 (Tier 3: 60%)
        t3 = evaluate_tech_cash_gate(cyb_close=2480.0, cyb_ma20=2500.0, cyb_ma60=2450.0, tech_breadth_ma20=0.45)
        self.assertEqual(t3["tier"], 3)
        self.assertEqual(t3["position_ratio"], 0.6)

        # 4. 科技全力进攻 (Tier 4: 100%)
        t4 = evaluate_tech_cash_gate(cyb_close=2700.0, cyb_ma20=2650.0, cyb_ma60=2500.0, tech_breadth_ma20=0.65)
        self.assertEqual(t4["tier"], 4)
        self.assertEqual(t4["position_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
