import unittest
from pathlib import Path
import tempfile
import sqlite3

from trading_plans import save_plan, list_plans, get_plan

class TestTradingPlans(unittest.TestCase):
    def test_crud_and_pin(self):
        # 1. 创建计划
        created = save_plan({
            "title": "视源股份低吸计划",
            "code": "002841",
            "name": "视源股份",
            "date": "2026-11-09",
            "direction": "买入",
            "target_price": 42.10,
            "stop_loss": 41.49,
            "target_profit": 44.50,
            "planned_position": "2成仓",
            "strategy_tag": "策略1·援军战法",
            "content": "开盘若回踩42.10附近低吸，止损41.49",
            "pinned": False,
        })
        pid = created["id"]
        self.assertTrue(pid)
        self.assertEqual(created["code"], "002841")
        self.assertEqual(created["direction"], "买入")
        self.assertFalse(created["pinned"])

        # 2. 置顶计划
        pinned_res = save_plan({"id": pid, "action": "toggle_pin"})
        self.assertTrue(pinned_res["pinned"])

        # 3. 列表查询，置顶的排最前面
        plans = list_plans()
        self.assertTrue(len(plans) >= 1)
        self.assertEqual(plans[0]["id"], pid)

        # 4. 状态切换
        stat_res = save_plan({"id": pid, "action": "toggle_status", "status": "executed"})
        self.assertEqual(stat_res["status"], "executed")

        # 5. 编辑更新内容
        updated = save_plan({
            "id": pid,
            "title": "视源股份已建仓跟踪",
            "code": "002841",
            "target_price": 42.10,
            "stop_loss": 41.49,
            "pinned": True,
            "status": "executed"
        })
        self.assertEqual(updated["title"], "视源股份已建仓跟踪")

        # 6. 删除计划
        del_res = save_plan({"id": pid, "action": "delete"})
        self.assertTrue(del_res["deleted"])
        self.assertIsNone(get_plan(pid))

if __name__ == "__main__":
    unittest.main()
