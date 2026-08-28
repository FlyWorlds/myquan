"""策略十二·竞价一字联动选股：注册与选股逻辑测试。"""

from __future__ import annotations

import unittest

import pandas as pd

import strategy.factors  # noqa: F401 — 仅注册因子
import strategy.strategies.strategy12  # noqa: F401
from strategy.auction_yizi_linkage import (
    daily_linkage_picks,
    is_one_word_at_open,
)
from strategy.core.strategy_registry import get_strategy_spec, resolve_strategy_id


class AuctionYiziLinkageTests(unittest.TestCase):
    def test_strategy12_registered(self) -> None:
        spec = get_strategy_spec("strategy12")
        self.assertEqual(spec.id, "strategy12")
        self.assertEqual(resolve_strategy_id("竞价一字联动"), "strategy12")
        self.assertEqual(resolve_strategy_id("s12"), "strategy12")
        self.assertIn("factor14", spec.factor_ids)

    def test_one_word_at_open(self) -> None:
        self.assertTrue(is_one_word_at_open(11.0, 11.0, 11.0))
        self.assertFalse(is_one_word_at_open(10.5, 10.2, 11.0))

    def test_daily_linkage_picks_basic(self) -> None:
        day = pd.DataFrame(
            [
                {
                    "symbol": "000001.SZ",
                    "name": "锚点",
                    "pre_close": 10.0,
                    "open": 11.0,
                    "high": 11.0,
                    "low": 11.0,
                    "close": 11.0,
                    "limit_up": 11.0,
                },
                {
                    "symbol": "000002.SZ",
                    "name": "联动A",
                    "pre_close": 10.0,
                    "open": 10.5,
                    "high": 10.8,
                    "low": 10.4,
                    "close": 10.7,
                    "limit_up": 11.0,
                },
                {
                    "symbol": "000003.SZ",
                    "name": "联动B",
                    "pre_close": 10.0,
                    "open": 10.8,
                    "high": 10.9,
                    "low": 10.6,
                    "close": 10.85,
                    "limit_up": 11.0,
                },
            ]
        )
        concepts = pd.DataFrame(
            {
                "concept": ["AI", "AI", "AI"],
                "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
                "in_date": ["2020-01-01", "2020-01-01", "2020-01-01"],
            }
        )
        stock_concepts = {
            "000001.SZ": {"AI"},
            "000002.SZ": {"AI"},
            "000003.SZ": {"AI"},
        }
        picks = daily_linkage_picks(day, stock_concepts, params={"top_k": 2, "min_open_gap": 0.03})
        self.assertEqual(picks[0], "000003.SZ")
        self.assertIn("000002.SZ", picks)


if __name__ == "__main__":
    unittest.main()
