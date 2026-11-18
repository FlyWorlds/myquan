"""单元测试：策略二·缠论图形形态全景扫描与类2买/1买判定。"""

import unittest
import pandas as pd
from holdingStocks.strategy2_watch import (
    analyze_chan_pattern,
    get_strategy2_watch_payload,
    get_strategy2_chart_data,
    run_strategy2_backtest,
    MANAGER,
)


class TestStrategy2Watch(unittest.TestCase):
    def test_semiconductor_pattern_detection(self) -> None:
        """验证半导体板块日线数据能否准确识别出 1买底背驰 与 类2买 结构。"""
        df = MANAGER._fetch_sector_daily("半导体")
        self.assertIsNotNone(df)
        self.assertFalse(df.empty)
        res = analyze_chan_pattern("881319", "半导体", df, is_sector=True)
        self.assertIsNotNone(res)
        # 精准匹配截图形态
        self.assertEqual(res.pattern, "buy2_prime")
        self.assertIn("类2买", res.pattern_label)
        self.assertIsNotNone(res.buy1_price)
        self.assertIsNotNone(res.pullback_low)
        self.assertGreaterEqual(res.pullback_low, res.buy1_price)  # 不破1买低点
        self.assertLessEqual(res.divergence_ratio, 0.88)  # MACD绿柱面积底背驰

    def test_chart_data_generation(self) -> None:
        """验证缠论图表数据生成（包含K线、笔、中枢与MACD）。"""
        chart = get_strategy2_chart_data("BK0475", "半导体", is_sector=True)
        self.assertIn("dates", chart)
        self.assertIn("kline", chart)
        self.assertIn("bi_lines", chart)
        self.assertIn("zs_boxes", chart)
        self.assertIn("macd", chart)
        self.assertIn("pattern_info", chart)
        self.assertTrue(len(chart["bi_lines"]) > 0)
        self.assertTrue(len(chart["macd"]["bar"]) > 0)

    def test_backtest_runner(self) -> None:
        """验证类2买历史回测引擎执行正常。"""
        bt = run_strategy2_backtest({
            "universe": "sectors",
            "take_profit_pct": 0.15,
            "stop_loss_pct": 0.05,
            "max_hold_days": 20,
        })
        self.assertEqual(bt.get("status"), "ok")
        self.assertIn("summary", bt)
        self.assertGreater(bt["summary"]["total_trades"], 0)


if __name__ == "__main__":
    unittest.main()
