"""当日止损禁再买 / 盘中隔夜均可持3 / 日最多2买 — 单测。"""
from __future__ import annotations

import unittest
from datetime import datetime

from watch_config import (
    MAX_ACTIVE_SLOTS,
    MAX_BUYS_PER_DAY,
    MAX_OVERNIGHT_SLOTS,
    MAX_PORTFOLIO_SLOTS,
    RESERVE_EMPTY_SLOTS,
    free_buy_slot_count,
    free_slot_count,
    slot_meta,
)


class TestSlotReserve(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(MAX_PORTFOLIO_SLOTS, 3)
        self.assertEqual(RESERVE_EMPTY_SLOTS, 0)
        self.assertEqual(MAX_OVERNIGHT_SLOTS, 3)
        self.assertEqual(MAX_ACTIVE_SLOTS, 3)  # 兼容旧名=隔夜上限
        self.assertEqual(MAX_BUYS_PER_DAY, 2)

    def test_free_buy_midday_allows_third(self):
        """持 2 仍可再买 1（到 3）；尾盘与盘中同上限。"""
        h = {
            "positions": {
                "600330": {"qty": 100},
                "002104": {"qty": 200},
            }
        }
        self.assertEqual(free_slot_count(h), 1)
        self.assertEqual(free_buy_slot_count(h, reserve_for_close=False), 1)
        self.assertEqual(free_buy_slot_count(h, reserve_for_close=True), 1)
        m = slot_meta(h, now=datetime(2026, 9, 8, 10, 0))
        self.assertEqual(m["freeBuy"], 1)
        self.assertEqual(m["overnightMax"], 3)
        m2 = slot_meta(h, now=datetime(2026, 9, 8, 14, 50))
        self.assertEqual(m2["freeBuy"], 1)
        self.assertTrue(m2["reserveWindow"])

    def test_three_holds_no_buy(self):
        h = {
            "positions": {
                "600330": {"qty": 100},
                "002104": {"qty": 200},
                "600301": {"qty": 100},
            }
        }
        self.assertEqual(free_buy_slot_count(h, reserve_for_close=False), 0)
        self.assertEqual(free_buy_slot_count(h, reserve_for_close=True), 0)


class TestSoldTodayBan(unittest.TestCase):
    def test_apply_trigger_sold_today_bans_rebuy(self):
        from index import _apply_trigger_date_fields

        row = {
            "持仓状态": "已平仓",
            "预警": "止损",
            "已触买": "否",
            "买点": 10.5,
            "止损": 9.8,
            "成交价": 9.8,
        }
        sig = {
            "hit_buy": False,
            "hit_stop": True,
            "因子触发": "已触发",
            "持仓状态": "已平仓",
        }
        _apply_trigger_date_fields(
            row,
            sig=sig,
            session="2026-09-07",
            last_px=10.2,
            px_digits=2,
            buy_time="2026-09-05",
            qty=0,
            replay={"holding": False},
            code="600330",
            allow_entry=True,
        )
        self.assertTrue(row.get("当日禁买"))


if __name__ == "__main__":
    unittest.main()
