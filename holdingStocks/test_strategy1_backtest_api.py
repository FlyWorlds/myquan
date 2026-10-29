from __future__ import annotations

import unittest
from holdingStocks.strategy1_backtest_service import Strategy1BacktestManager, calculate_7d_comparison
import pandas as pd


class TestStrategy1BacktestService(unittest.TestCase):
    def test_calculate_7d_comparison(self):
        equity_rows = [
            {"date": "2026-10-20", "equity": 302074.14, "ret_pct": 0.69},
            {"date": "2026-10-21", "equity": 302108.79, "ret_pct": 0.70},
            {"date": "2026-10-22", "equity": 301637.80, "ret_pct": 0.55},
            {"date": "2026-10-23", "equity": 303902.20, "ret_pct": 1.30},
            {"date": "2026-10-26", "equity": 300792.67, "ret_pct": 0.26},
            {"date": "2026-10-27", "equity": 296530.82, "ret_pct": -1.16},
            {"date": "2026-10-28", "equity": 306038.53, "ret_pct": 2.01},
        ]
        sh_df = pd.DataFrame([
            {"date": "2026-10-20", "open": 3718.436, "close": 3735.37, "high": 3740.072, "low": 3702.444, "volume": 100},
            {"date": "2026-10-21", "open": 3740.568, "close": 3713.028, "high": 3743.085, "low": 3703.125, "volume": 100},
            {"date": "2026-10-22", "open": 3714.476, "close": 3658.026, "high": 3714.476, "low": 3649.865, "volume": 100},
            {"date": "2026-10-23", "open": 3623.567, "close": 3690.475, "high": 3691.399, "low": 3574.271, "volume": 100},
            {"date": "2026-10-26", "open": 3671.004, "close": 3697.520, "high": 3699.010, "low": 3664.821, "volume": 100},
            {"date": "2026-10-27", "open": 3698.441, "close": 3648.301, "high": 3708.198, "low": 3648.301, "volume": 100},
            {"date": "2026-10-28", "open": 3676.919, "close": 3681.469, "high": 3684.491, "low": 3652.366, "volume": 100},
        ])
        res = calculate_7d_comparison(equity_rows, sh_df)
        self.assertEqual(len(res["dates"]), 7)
        self.assertEqual(len(res["strategy_cum_pct"]), 7)
        self.assertEqual(len(res["sh_cum_x2_pct"]), 7)
        self.assertEqual(len(res["sh_kline"]), 7)
        self.assertAlmostEqual(res["metrics"]["strategy_final_return"], 2.01, places=1)
        self.assertAlmostEqual(res["metrics"]["alpha"], res["metrics"]["strategy_final_return"] - res["metrics"]["sh_final_return_x2"], places=2)

    def test_manager_get_status(self):
        status = Strategy1BacktestManager.get_status()
        self.assertIn("running", status)
        self.assertIn("latest", status)
        self.assertIsNotNone(status["latest"])
        self.assertIn("dates", status["latest"])
        self.assertIn("strategy_cum_pct", status["latest"])
        self.assertIn("sh_cum_x2_pct", status["latest"])


if __name__ == "__main__":
    unittest.main()
