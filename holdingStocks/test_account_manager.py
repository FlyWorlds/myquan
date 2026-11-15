import unittest
from pathlib import Path
from holdingStocks.account_manager import (
    DEFAULT_ACCOUNT_ID,
    get_accounts_config,
    list_accounts_summary,
    create_account,
    update_account,
    delete_account,
    set_active_account_id,
    format_account_tag,
    get_account_holdings_data,
)


class TestAccountManager(unittest.TestCase):
    def test_default_account_exists(self):
        cfg = get_accounts_config()
        self.assertIn("accounts", cfg)
        acc_ids = [a["id"] for a in cfg["accounts"]]
        self.assertIn(DEFAULT_ACCOUNT_ID, acc_ids)

    def test_list_accounts_summary(self):
        summary = list_accounts_summary()
        self.assertTrue(len(summary) >= 1)
        default_acc = next((a for a in summary if a["id"] == DEFAULT_ACCOUNT_ID), None)
        self.assertIsNotNone(default_acc)
        self.assertTrue(default_acc["is_default"])
        self.assertEqual(default_acc["type"], "long_term")

    def test_create_and_delete_account(self):
        new_acc = create_account({
            "name": "测试短线账户",
            "type": "short_term",
            "initial_capital": 150000.0,
            "mounted_strategies": ["strategy38"],
            "risk_rules": {"stop_loss_pct": -0.03},
        })
        new_id = new_acc["id"]
        self.assertTrue(new_id.startswith("acc_short_"))
        self.assertEqual(new_acc["name"], "测试短线账户")
        self.assertEqual(new_acc["risk_rules"]["stop_loss_pct"], -0.03)

        # 检查专属持仓账本
        h = get_account_holdings_data(new_id)
        self.assertEqual(h["account_cash"], 150000.0)

        # 测试更新
        updated = update_account(new_id, {"name": "改名短线账户", "initial_capital": 180000.0})
        self.assertEqual(updated["name"], "改名短线账户")
        self.assertEqual(updated["initial_capital"], 180000.0)

        # 测试标签
        tag = format_account_tag(new_id)
        self.assertEqual(tag, "【改名短线账户】")

        # 测试默认账户不可删除
        with self.assertRaises(ValueError):
            delete_account(DEFAULT_ACCOUNT_ID)

        # 删除新建账户
        res = delete_account(new_id)
        self.assertEqual(res["status"], "success")

        # 再次确认已被删除
        cfg = get_accounts_config()
        self.assertNotIn(new_id, [a["id"] for a in cfg["accounts"]])


if __name__ == "__main__":
    unittest.main()
