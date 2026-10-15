import copy
import unittest
from datetime import datetime

from condition_order_report import comparison_report, comparison_csv


class ConditionOrderReportTest(unittest.TestCase):
    def snapshot(self):
        return {"conditionBuy": {"enabled": True, "session": "2026-10-16", "orders": [
            {"id": "one", "session": "2026-10-16", "code": "002580", "name": "=unsafe",
             "status": "ARMED", "price": 19.25, "open": 19, "entry_pct": .025,
             "armed_at": "2026-10-16 09:25:02", "gate": "pass"}]}}

    def test_export_does_not_change_orders_or_recalculate_price(self):
        snap = self.snapshot()
        before = copy.deepcopy(snap)
        report = comparison_report(snap, datetime(2026, 10, 16, 9, 26))
        self.assertTrue(report["ready"])
        self.assertFalse(report["complete"])
        self.assertEqual(report["orders"][0]["target_price"], 19.25)
        self.assertEqual(snap, before)

    def test_previous_day_and_preauction_are_not_ready(self):
        for now in (datetime(2026, 10, 17, 9, 26), datetime(2026, 10, 16, 9, 24)):
            report = comparison_report(self.snapshot(), now)
            self.assertFalse(report["ready"])
            self.assertEqual(report["orders"], [])

    def test_missing_snapshot_not_ready(self):
        self.assertFalse(comparison_report(None)["ready"])

    def test_blocked_and_filled_remain_labelled_not_new_recommendations(self):
        snap = self.snapshot()
        snap["conditionBuy"]["orders"][0]["status"] = "BLOCKED"
        report = comparison_report(snap, datetime(2026, 10, 16, 9, 26))
        self.assertEqual(report["orders"][0]["status"], "BLOCKED")

    def test_csv_preserves_code_and_escapes_formula(self):
        body = comparison_csv(comparison_report(self.snapshot(), datetime(2026, 10, 16, 9, 26)))
        self.assertTrue(body.startswith(b"\xef\xbb\xbf"))
        self.assertIn("'002580", body.decode("utf-8-sig"))
        self.assertIn("'=unsafe", body.decode("utf-8-sig"))
