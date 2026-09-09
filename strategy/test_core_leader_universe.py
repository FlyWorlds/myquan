"""核心龙头选股：过滤 / 偏高概念 / 每概念 TopK（无通达信依赖）。"""

from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from strategy.core_leader_universe import (
    build_quarter_pool,
    rolling_3m_window,
    is_core_leader_board,
    is_st_name,
    passes_stock_filter,
    pick_leaders_from_members,
    select_hot_concepts,
)


class TestCoreLeaderUniverse(unittest.TestCase):
    def test_board_and_st_filters(self):
        self.assertTrue(is_core_leader_board("600000"))
        self.assertTrue(is_core_leader_board("000001"))
        self.assertFalse(is_core_leader_board("300001"))
        self.assertFalse(is_core_leader_board("688001"))
        self.assertFalse(is_core_leader_board("830001"))
        self.assertFalse(is_core_leader_board("920019"))
        self.assertTrue(is_st_name("*ST长油"))
        self.assertTrue(is_st_name("ST假"))
        self.assertFalse(is_st_name("贵州茅台"))
        self.assertTrue(passes_stock_filter("600000", "浦发银行", 8.5))
        self.assertFalse(passes_stock_filter("600000", "浦发银行", 100))
        self.assertFalse(passes_stock_filter("300750", "宁德时代", 80))
        self.assertFalse(passes_stock_filter("600000", "*ST示例", 8.5))

    def test_select_hot_concepts_above_median_then_topn(self):
        spot = pd.DataFrame(
            [
                {"板块": "冷门A", "资金": 10, "涨跌幅": 1},
                {"板块": "冷门B", "资金": 20, "涨跌幅": 1},
                {"板块": "中位", "资金": 30, "涨跌幅": 1},
                {"板块": "热1", "资金": 90, "涨跌幅": 2},
                {"板块": "热2", "资金": 80, "涨跌幅": 2},
                {"板块": "热3", "资金": 70, "涨跌幅": 2},
            ]
        )
        hot = select_hot_concepts(spot, max_concepts=2)
        self.assertEqual([x["name"] for x in hot], ["热1", "热2"])
        self.assertEqual(hot[0]["activity"], 90)

    def test_skip_style_concepts(self):
        spot = pd.DataFrame(
            [
                {"板块": "基金重仓", "资金": 200, "涨跌幅": 1},
                {"板块": "光通信模块", "资金": 180, "涨跌幅": 2},
                {"板块": "标准普尔", "资金": 170, "涨跌幅": 1},
                {"板块": "中证500", "资金": 160, "涨跌幅": 1},
            ]
        )
        hot = select_hot_concepts(spot, max_concepts=15)
        self.assertEqual([x["name"] for x in hot], ["光通信模块"])

    def test_per_concept_top2_after_filter(self):
        members = pd.DataFrame(
            [
                {"代码": "300001", "名称": "创业票", "现价": 10, "涨跌幅": 9, "成交额": 9e8},
                {"代码": "600001", "名称": "龙头甲", "现价": 12, "涨跌幅": 8, "成交额": 3e8},
                {"代码": "600002", "名称": "*ST乙", "现价": 5, "涨跌幅": 20, "成交额": 9e8},
                {"代码": "600003", "名称": "龙头丙", "现价": 20, "涨跌幅": 7, "成交额": 2e8},
                {"代码": "600004", "名称": "龙头丁", "现价": 15, "涨跌幅": 6, "成交额": 1e8},
                {"代码": "600005", "名称": "百元", "现价": 120, "涨跌幅": 10, "成交额": 9e8},
                {"代码": "600006", "名称": "第五", "现价": 9, "涨跌幅": 1, "成交额": 1e8},
            ]
        )
        picks = pick_leaders_from_members(members, concept="测试概念", per_concept=2)
        self.assertEqual([x["code"] for x in picks], ["600001", "600003"])
        self.assertEqual([x["rank_in_concept"] for x in picks], [1, 2])

    def test_build_pool_dedup_across_concepts(self):
        spot = pd.DataFrame(
            [
                {"板块": "冷门", "资金": 10, "涨跌幅": 0},
                {"板块": "概念甲", "资金": 100, "涨跌幅": 3},
                {"板块": "概念乙", "资金": 90, "涨跌幅": 2},
            ]
        )
        members = {
            "概念甲": pd.DataFrame(
                [{"代码": "600001", "名称": "共享龙头", "现价": 10, "涨跌幅": 5, "成交额": 1e8}]
            ),
            "概念乙": pd.DataFrame(
                [
                    {"代码": "600001", "名称": "共享龙头", "现价": 10, "涨跌幅": 5, "成交额": 1e8},
                    {"代码": "600002", "名称": "乙龙头", "现价": 8, "涨跌幅": 4, "成交额": 1e8},
                ]
            ),
        }
        payload = build_quarter_pool(
            today=date(2026, 9, 9),
            spot=spot,
            members_by_concept=members,
            fetch=False,
            max_concepts=2,
            per_concept=2,
        )
        self.assertEqual(payload["horizon"], "rolling_3m")
        self.assertEqual(payload["label"], "2026-06-09~2026-09-09")
        self.assertEqual(payload["valid_until"], "2026-12-09")
        self.assertEqual([x["code"] for x in payload["picks"]], ["600001", "600002"])
        self.assertIn("概念乙", str(payload["picks"][0].get("concepts") or ""))

    def test_target_pool_stops_at_30(self):
        spot = pd.DataFrame(
            [{"板块": f"概念{i}", "资金": 200 - i, "涨跌幅": 1} for i in range(20)]
        )
        members = {
            f"概念{i}": pd.DataFrame(
                [
                    {
                        "代码": f"{600000 + i * 3 + j}",
                        "名称": f"票{i}_{j}",
                        "现价": 10,
                        "涨跌幅": 5 - j,
                        "成交额": 1e8,
                    }
                    for j in range(3)
                ]
            )
            for i in range(20)
        }
        payload = build_quarter_pool(
            today=date(2026, 9, 9),
            spot=spot,
            members_by_concept=members,
            fetch=False,
            max_concepts=20,
            per_concept=2,
            target_pool=30,
        )
        self.assertEqual(payload["n_picks"], 30)
        self.assertEqual(payload["per_concept"], 2)
        self.assertGreaterEqual(payload["n_used_concepts"], 15)

    def test_rolling_3m_window(self):
        w = rolling_3m_window(date(2026, 9, 9))
        self.assertEqual(w["window_start"], "2026-06-09")
        self.assertEqual(w["window_end"], "2026-09-09")
        self.assertEqual(w["valid_until"], "2026-12-09")
        self.assertEqual(w["label"], "2026-06-09~2026-09-09")


if __name__ == "__main__":
    unittest.main()
