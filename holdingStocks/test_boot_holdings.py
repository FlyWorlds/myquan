from __future__ import annotations

import copy
import unittest
from unittest.mock import Mock, patch

from account_reconciliation import AccountReadModel
from boot_holdings import build_boot_holdings


class BootHoldingsTests(unittest.TestCase):
    def state(self):
        return dict(revision=4, holdings=dict(account_cash=1000, paper_equity_base=2000,
                  positions={"002841": dict(qty=100, cost=10, name="Test", buy_time="2026-10-14 10:00:00"),
                             "600072": dict(qty=0,cost=None)}), trades=[], ledger={"entries":[]})

    def test_inventory_appears_without_quotes_or_daily_reads(self):
        state=self.state()
        original=copy.deepcopy(state)
        rows,account=build_boot_holdings(AccountReadModel(state),session="2026-10-14",clock="2026-10-14 15:30:00")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["持仓"],100)
        self.assertTrue(rows[0]["置顶"])
        self.assertIsNone(rows[0]["现价"])
        self.assertIsNone(account["accountTotal"])
        self.assertEqual(account["availableCash"],1000)
        self.assertEqual(state,original)

    def test_live_quotes_update_valuation_but_not_buy_sell_signals(self):
        quote=dict(session="2026-10-14",last_ts="2026-10-14 15:00:00",last=11,prev_close=10,
                   open=10,high=12,day_chg_pct=10,_quote_source="sina")
        rows,account=build_boot_holdings(AccountReadModel(self.state()),session="2026-10-14",
                                      clock="2026-10-14 15:30:00",get_quote=lambda _:quote)
        self.assertEqual(account["accountTotal"],2100)
        self.assertEqual(account["totalPnl"],100)
        self.assertEqual(rows[0]["已触买"],"否")
        self.assertIsNone(rows[0]["买点"])
        self.assertIsNone(rows[0]["止损"])

    def test_stale_future_daily_or_unavailable_quote_never_invents_valuation(self):
        for quote in [dict(session="2026-10-13",last_ts="2026-10-13 15:00:00",last=11),
                      dict(session="2026-10-14",last_ts="2026-10-14 16:00:00",last=11),
                      dict(session="2026-10-14",last_ts="2026-10-14 15:00:00",last=11,_quote_source="daily_prev")]:
            rows,account=build_boot_holdings(AccountReadModel(self.state()),session="2026-10-14",
                    clock="2026-10-14 15:30:00",get_quote=lambda _:quote)
            self.assertIsNone(rows[0]["现价"])
            self.assertIsNone(account["accountTotal"])

    def test_preview_does_not_write_or_replace_a_completed_snapshot(self):
        import index
        model=AccountReadModel(self.state())
        store=Mock()
        store.read_model.return_value=model
        with patch.object(index,"_HOLDINGS_STORE",store), patch.object(index,"_last_watch_snapshot",{"boot":True}), \
             patch.object(index,"_calendar_signal_session",return_value="2026-10-14"), \
             patch.object(index,"_now",return_value="2026-10-14 15:30:00"), \
             patch.object(index,"_broadcast_watch_snapshot"), patch.object(index,"_stamp_snapshot_liveness",side_effect=lambda s:s):
            self.assertTrue(index._publish_boot_holdings_preview())
            self.assertTrue(index._last_watch_snapshot["boot"])
            self.assertTrue(index._last_watch_snapshot["blockTrading"])
            self.assertEqual(index._last_watch_snapshot["paperRevision"],4)
            self.assertEqual(index._last_watch_snapshot["slotMeta"]["free"], index.MAX_POSITION_SYMBOLS-1)
            store.save.assert_not_called()
            index._last_watch_snapshot={"boot":False,"holdings":[{"现价":999}]}
            self.assertFalse(index._publish_boot_holdings_preview())
            self.assertEqual(index._last_watch_snapshot["holdings"][0]["现价"],999)

    def test_many_rows_use_one_revision_and_one_corrected_index(self):
        import index
        store=Mock()
        model=AccountReadModel(self.state())
        store.read_model.return_value=model
        snapshot={"paperRevision":4,"holdings":[],"strategy16":[{"代码":"002841","现价":11} for _ in range(100)]}
        with patch.object(index,"database_enabled",return_value=True), patch.object(index,"_HOLDINGS_STORE",store), \
             patch("account_reconciliation.effective_deliveries",side_effect=AssertionError("repeated index build")):
            index._enrich_snapshot_comprehensive_trade_returns(snapshot)
            store.read_model.assert_called_once()
            store.snapshot.assert_not_called()
            snapshot["paperRevision"]=3
            with patch.object(index,"_enrich_comprehensive_trade_return",side_effect=AssertionError("mixed revision")):
                self.assertFalse(index._enrich_snapshot_comprehensive_trade_returns(snapshot))


if __name__=="__main__":
    unittest.main()
