"""策略三十八·地量起爆多维选股 完整功能与四步漏斗单测。"""

from __future__ import annotations

import unittest
import pandas as pd
import numpy as np

from strategy.core.strategy_registry import get_strategy_spec
from strategy.strategies.strategy38.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME
from strategy.strategies.strategy38.decision import Strategy38Decision, create_decision_engine
from strategy.strategies.strategy38.pipeline import (
    evaluate_market_cash_gate,
    filter_quality_pool,
    generate_execution_orders,
    run_strategy38_pipeline,
    scan_breakout_momentum,
)


class TestStrategy38(unittest.TestCase):
    def test_strategy_spec_and_registration(self) -> None:
        spec = get_strategy_spec(STRATEGY_ID)
        self.assertEqual(spec.id, STRATEGY_ID)
        self.assertEqual(spec.name, STRATEGY_NAME)
        self.assertTrue(spec.implemented)
        self.assertTrue(spec.meta.get("watch_tab"))
        self.assertIn("s38", spec.aliases)
        self.assertIn("地量起爆", spec.aliases)

        rules = spec.print_rules()
        self.assertIn("策略三十八·地量起爆多维选股", rules)
        self.assertIn("factor35", rules)
        self.assertIn("factor13a", rules)
        self.assertIn("factor34", rules)
        self.assertIn("factor8", rules)
        self.assertIn("factor33", rules)

    def test_step1_veto_cash_gate(self) -> None:
        """Step 1: 绝对风控（一票否决）"""
        # 场景 A: 极端踩踏（广度 8% < 12% 熔断线）
        res_panic = evaluate_market_cash_gate(
            close_price=3800.0,
            ma20=3820.0,
            ma60=3850.0,
            market_breadth_ma20=0.08,
            current_cash_state=False,
        )
        self.assertTrue(res_panic["veto_cash"])
        self.assertEqual(res_panic["status"], "VETO_CASH")
        self.assertEqual(res_panic["position_ratio"], 0.0)

        # 场景 B: 指数跌破 MA60 生命线且广度 20% < 28%（破位防守态）
        res_broken = evaluate_market_cash_gate(
            close_price=3650.0,
            ma20=3700.0,
            ma60=3800.0,
            market_breadth_ma20=0.20,
            current_cash_state=False,
        )
        self.assertTrue(res_broken["veto_cash"])
        self.assertEqual(res_broken["status"], "VETO_CASH")

        # 场景 C: 大盘稳健进攻态
        res_ok = evaluate_market_cash_gate(
            close_price=3950.0,
            ma20=3900.0,
            ma60=3850.0,
            market_breadth_ma20=0.65,
            current_cash_state=False,
        )
        self.assertFalse(res_ok["veto_cash"])
        self.assertEqual(res_ok["status"], "PASS")
        self.assertEqual(res_ok["position_ratio"], 1.0)

    def test_step2_quality_pool_filtering(self) -> None:
        """Step 2: 底池清洗（基本面过滤）"""
        raw_stocks = [
            {"code": "600519", "name": "贵州茅台", "close": 1700.0, "amount": 5e8},
            {"code": "601127", "name": "赛力斯", "close": 88.0, "amount": 3e8},
            {"code": "600999", "name": "*ST招金", "close": 5.0, "amount": 2e7},    # ST过滤
            {"code": "000001", "name": "退市碳素", "close": 1.2, "amount": 1e6},    # 退市过滤
            {"code": "300750", "name": "宁德时代", "close": 260.0, "amount": 8e8},  # 创业板过滤
            {"code": "688981", "name": "中芯国际", "close": 90.0, "amount": 4e8},   # 科创板过滤
            {"code": "002466", "name": "天齐锂业", "close": 38.0, "amount": 2e8},   # 主板通过
            {"code": "600001", "name": "微盘僵尸", "close": 2.0, "amount": 1e5},    # 超低价低量过滤
        ]

        cleaned = filter_quality_pool(raw_stocks, min_price=3.0, max_price=1500.0, min_volume=1e7)
        cleaned_codes = {s["code"] for s in cleaned}

        self.assertIn("601127", cleaned_codes)
        self.assertIn("002466", cleaned_codes)
        self.assertNotIn("600999", cleaned_codes)  # ST 剔除
        self.assertNotIn("000001", cleaned_codes)  # 退市 剔除
        self.assertNotIn("300750", cleaned_codes)  # 创业板 剔除
        self.assertNotIn("688981", cleaned_codes)  # 科创板 剔除
        self.assertNotIn("600001", cleaned_codes)  # 价格/流动性不达标 剔除

    def test_step3_and_step4_pipeline_execution(self) -> None:
        """Step 3 形态筛选 与 Step 4 买点生成"""
        dates = pd.date_range("2026-01-01", periods=75, freq="B")
        closes = [20.0] * 68
        opens = [20.0] * 68
        volumes = [10000.0] * 68

        # 构造地量 anchor：倒数第5天成交量 2000 (60日最低)
        closes.append(19.8)
        opens.append(19.9)
        volumes.append(2000.0)

        # 倒数第4天：过渡十字星
        closes.append(19.85)
        opens.append(19.8)
        volumes.append(2200.0)

        # 倒数第3天：倍量大阳线起爆！放量 3.0倍 (6000)，实体大涨 +7.0%
        breakout_open = 19.85
        breakout_close = breakout_open * 1.07
        closes.append(breakout_close)
        opens.append(breakout_open)
        volumes.append(6000.0)

        # 倒数第2天与第1天：小幅休整
        closes.append(breakout_close * 1.005)
        opens.append(breakout_close * 0.998)
        volumes.append(4000.0)

        closes.append(breakout_close * 1.01)
        opens.append(breakout_close * 1.002)
        volumes.append(3800.0)

        highs = [max(o, c) * 1.01 for o, c in zip(opens, closes)]
        lows = [min(o, c) * 0.99 for o, c in zip(opens, closes)]

        df = pd.DataFrame({
            "date": [d.strftime("%Y-%m-%d") for d in dates[-len(closes):]],
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "amount": [c * v for c, v in zip(closes, volumes)],
        })
        df.attrs["name"] = "起爆测试股"

        stock_bars = {"600123": df}
        candidates = scan_breakout_momentum(stock_bars, lookback=60, max_age=10, volume_multiple=2.0, body_min=0.05)
        self.assertEqual(len(candidates), 1)

        cand = candidates[0]
        self.assertEqual(cand["code"], "600123")
        self.assertAlmostEqual(cand["volume_ratio"], 3.0, places=1)
        self.assertGreaterEqual(cand["body_return"], 0.05)

        # Step 4: 买点生成
        orders = generate_execution_orders(candidates, threshold_pct=0.025, tick=0.01)
        self.assertEqual(len(orders), 1)
        order = orders[0]

        # 验证突破触发买点高于最新收盘
        self.assertGreater(order["buy_trigger_price"], cand["last_close"])
        # 验证回踩买点为起爆大阳二分位
        expected_support = round((cand["breakout_open"] + cand["breakout_close"]) / 2.0, 2)
        self.assertEqual(order["support_buy_price"], expected_support)
        # 验证止损保护价低于起爆最低价
        self.assertLess(order["stop_loss_price"], cand["breakout_low"])
        self.assertIn("缠论底分型向上笔", order["confirm_logic"])

    def test_pipeline_veto_full_flow(self) -> None:
        """验证风控触发时，整体选股流程一票否决"""
        macro_bad = {"close": 3600.0, "ma20": 3700.0, "ma60": 3800.0, "breadth": 0.10}
        res = run_strategy38_pipeline(macro_data=macro_bad)
        self.assertTrue(res["step1_cash_gate"]["veto_cash"])
        self.assertEqual(res["step2_quality_pool"]["count"], 0)
        self.assertEqual(len(res["step3_breakout_candidates"]), 0)
        self.assertEqual(len(res["step4_orders"]), 0)
        self.assertIn("一票否决", res["summary"])

    def test_decision_engine(self) -> None:
        """测试策略三十八决策引擎接口"""
        from strategy.core.context import MarketContext

        engine = create_decision_engine()
        self.assertIsInstance(engine, Strategy38Decision)

        # 极端熔断环境 -> HOLD
        bad_ctx = MarketContext(
            open=10.0,
            high=10.1,
            low=9.9,
            close=10.0,
            meta={"index_close": 3500.0, "index_ma60": 3700.0, "market_breadth_ma20": 0.10, "code": "600123"},
        )
        d_hold = engine.decide(bad_ctx)
        self.assertEqual(d_hold.action, "hold")
        self.assertIn("一票否决", d_hold.reason)


if __name__ == "__main__":
    unittest.main()
