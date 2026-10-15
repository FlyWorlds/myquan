"""Reference reads and reconciliation must never turn into trading writes."""
import copy
import unittest
from unittest.mock import patch

from audit_database_account import audit, coherent_database_read


class TestDataReadBoundaries(unittest.TestCase):
    def setUp(self):
        self.state = dict(revision=7, holdings=dict(last_session="2026-10-15", account_cash=1000,
            paper_equity_base=2000, account_total_open=2000, account_total_open_session="2026-10-15",
            positions={"000070": dict(qty=100, cost=10, buy_time="2026-10-14 10:00:00")}),
            trades=[], ledger=dict(entries=[dict(id="buy", side="buy", code="000070", qty=100,
                after_qty=100, price=10, amount=1000, time="2026-10-14 10:00:00")]))
        self.quotes = {"sz000070": dict(session="2026-10-15", last=11., prev_close=10., open=10.,
            high=11., low=10., last_ts="2026-10-15 10:00:00", _quote_source="sina_batch",
            _source_time_verified=True, _database_quote_revision=2)}
        self.snapshot = dict(paperRevision=7, holdings=[{"代码":"000070", "持仓":100, "成本":10.,
            "现价":11., "更新":"2026-10-15 10:00:00", "报价数据库版本":2}],
            account=dict(availableCash=1000, accountTotal=2100, totalPnl=100, dayPnl=100, positionPct=52.4))
        self.books = {"000070": dict(revision=3, history_status="new_database_ledger", initial_cash=100000,
            virtual_cash=90000, virtual_shares=1000, entry_price=10, last_mark=11, single_cost_base=10000,
            single_realized_pnl=0, total_pnl=1000, unrealized_pnl=1000, realized_pnl=0, cycle_pnl=1000,
            since_checkpoint_pnl=1000, cumulative_return_pct=1, cycle_return_pct=10, single_return_pct=10)}

    def audit(self):
        return audit(self.state, self.snapshot, self.books, self.quotes, clock="2026-10-15 10:01:00")

    def test_database_is_the_basis_and_audit_never_changes_any_input(self):
        original = copy.deepcopy((self.state, self.snapshot, self.books, self.quotes))
        result = self.audit()
        self.assertTrue(result["complete"])
        self.assertEqual(result["account"]["accountTotal"], 2100)
        self.assertFalse(result["writesPerformed"])
        self.assertFalse(result["eventHistoryChecked"])
        self.assertEqual((self.state, self.snapshot, self.books, self.quotes), original)

    def test_old_page_is_pending_not_a_database_arithmetic_error(self):
        self.snapshot["paperRevision"] = 6
        self.snapshot["holdings"][0]["现价"] = 999
        result = self.audit()
        self.assertEqual(result["account"]["accountTotal"], 2100)
        self.assertTrue(result["operationalChecksPassed"])
        self.assertFalse(result["uiComparable"])
        self.assertEqual(result["uiIssues"], [])

    def test_same_second_quote_needs_same_database_quote_revision_to_compare(self):
        self.snapshot["holdings"][0]["报价数据库版本"] = 1
        result = self.audit()
        self.assertFalse(result["uiComparable"])
        self.assertEqual(result["uiIssues"], [])

    def test_same_revision_wrong_display_is_reported_without_repricing_fills(self):
        self.snapshot["holdings"][0]["现价"] = 999
        result = self.audit()
        self.assertTrue(result["uiComparable"])
        self.assertTrue(any(i["kind"] == "ui_row_mismatch" for i in result["uiIssues"]))
        self.assertEqual(self.state["ledger"]["entries"][0]["price"], 10)

    def test_repeated_full_sales_and_position_divergence_are_reported(self):
        for identity in ("sale-a", "sale-b"):
            self.state["ledger"]["entries"].append(dict(id=identity, side="sell", code="000070", qty=100,
                after_qty=0, price=11., cost=10., pnl=100., time="2026-10-15 10:00:00"))
        issues = self.audit()["deliveryIssues"]
        self.assertTrue(any(i["kind"] == "position_chain_gap" for i in issues))
        self.assertTrue(any(i["kind"] == "delivery_position_mismatch" for i in issues))

    def test_legacy_history_and_current_arithmetic_are_separate_audit_scopes(self):
        self.books["000070"]["history_status"] = "legacy_checkpoint_unverified"
        result = self.audit()
        self.assertTrue(result["operationalChecksPassed"])
        self.assertFalse(result["historyVerified"])
        self.assertFalse(result["complete"])
        self.books["000070"]["total_pnl"] = 14990
        self.assertTrue(self.audit()["strategyIssues"])

    def test_missing_reference_quote_is_unknown_not_zero_profit(self):
        self.quotes.clear()
        result = self.audit()
        self.assertIsNone(result["account"]["accountTotal"])
        self.assertIsNone(result["account"]["totalPnl"])
        self.assertEqual(result["account"]["availableCash"], 1000)

    def test_account_revision_change_requires_rereading_the_audit_inputs(self):
        newer = dict(self.state, revision=8)
        with patch("audit_database_account.request_state", side_effect=[self.state, newer, newer, newer]) as read, \
             patch("audit_database_account.read_quotes", return_value=self.quotes) as quotes, \
             patch("audit_database_account.request_books", return_value=self.books), \
             patch("audit_database_account.time.sleep"):
            state, _, _ = coherent_database_read()
        self.assertEqual(state["revision"], 8)
        self.assertEqual(read.call_count, 4)
        self.assertEqual(quotes.call_count, 2)


if __name__ == "__main__":
    unittest.main()
