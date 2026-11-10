import unittest
from project_todos import save_todo, list_todos, get_todo

class TestProjectTodos(unittest.TestCase):
    def test_todos_crud_and_status(self):
        created = save_todo({
            "title": "测试改造任务：接入自动风控阻断",
            "category": "风控止损",
            "priority": "P0",
            "status": "todo",
            "content": "当账户单日回撤达到2.5%时全局禁止新买单",
            "target_date": "2026-11-20",
            "pinned": True
        })
        tid = created["id"]
        self.assertTrue(tid)
        self.assertEqual(created["priority"], "P0")
        self.assertTrue(created["pinned"])

        # 状态切换
        stat_res = save_todo({"id": tid, "action": "toggle_status", "status": "in_progress"})
        self.assertEqual(stat_res["status"], "in_progress")

        # 置顶切换
        pin_res = save_todo({"id": tid, "action": "toggle_pin"})
        self.assertFalse(pin_res["pinned"])

        # 列表查询
        todos = list_todos()
        self.assertTrue(any(t["id"] == tid for t in todos))

        # 删除
        del_res = save_todo({"id": tid, "action": "delete"})
        self.assertTrue(del_res["deleted"])
        self.assertIsNone(get_todo(tid))

if __name__ == "__main__":
    unittest.main()
