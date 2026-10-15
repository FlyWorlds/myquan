from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from database_holdings import DatabaseHoldingsStore, DatabaseStateError


class DatabaseHoldingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "holdings.json"
        self.cache = {}
        self.store = DatabaseHoldingsStore(self.cache, path=lambda: self.path)
        self.state = dict(revision=1, holdings={"positions":{},"account_cash":10000}, trades=[], ledger={"entries":[]})

    def request(self, method="GET", payload=None, **kwargs):
        if method == "PUT":
            if payload["expectedRevision"] != self.state["revision"]:
                raise DatabaseStateError("conflict")
            self.state = dict(revision=self.state["revision"]+1,
                              **{key:copy.deepcopy(payload[key]) for key in ("holdings","trades","ledger")})
        return copy.deepcopy(self.state)

    def test_atomic_fill_preserves_identity_without_writing_local_files(self):
        with patch("database_holdings.request_state",side_effect=self.request):
            book=self.store.load()
            book["positions"]["002841"]={"qty":100,"cost":43.65}
            book["account_cash"]=5635
            self.store.save(book,records=[{"side":"buy","code":"002841","price":43.65,"qty":100,"after_qty":100}])
            self.assertIs(book,self.store.load())
            self.assertEqual(len(self.state["trades"]),1)
            self.assertEqual(len(self.state["ledger"]["entries"]),1)
            self.assertEqual(self.state["holdings"]["account_cash"],5635)
            self.assertFalse(self.path.exists())

    def test_nested_transaction_and_expired_cache_do_not_reload_pending_mutation(self):
        with patch("database_holdings.request_state",side_effect=self.request) as request:
            with self.store.transaction():
                book=self.store.load()
                book["account_cash"]=9000
                self.store._read_at=0
                with self.store.transaction():
                    self.assertEqual(self.store.load(force=True)["account_cash"],9000)
                    self.assertEqual(self.store.snapshot()["holdings"]["account_cash"],10000)
                self.assertEqual(request.call_count,1)
                self.store.save(book)
            self.assertEqual(self.state["holdings"]["account_cash"],9000)
            self.assertEqual(self.store._transaction_depth,0)

    def test_read_model_is_reused_until_committed_revision_changes(self):
        with patch("database_holdings.request_state",side_effect=self.request), \
             patch("account_reconciliation.effective_deliveries",wraps=__import__("account_reconciliation").effective_deliveries) as corrected:
            first=self.store.read_model()
            for _ in range(100):
                self.assertIs(self.store.read_model(),first)
            self.assertEqual(corrected.call_count,1)
            book=self.store.load()
            book["account_cash"]=9000
            self.assertEqual(self.store.read_model().state["holdings"]["account_cash"],10000)
            self.store.save(book)
            second=self.store.read_model()
            self.assertIsNot(second,first)
            self.assertEqual(second.state["holdings"]["account_cash"],9000)
            self.assertEqual(first.state["holdings"]["account_cash"],10000)
            self.assertEqual(corrected.call_count,2)

    def test_conflict_rolls_back_memory_instead_of_merging_cash(self):
        with patch("database_holdings.request_state",side_effect=self.request):
            book=self.store.load()
            book["account_cash"]=1
            self.state["revision"]=2
            with self.assertRaises(DatabaseStateError):self.store.save(book)
            self.assertEqual(book["account_cash"],10000)
            self.assertEqual(self.store.load(force=True)["account_cash"],10000)
            self.assertFalse(self.path.exists())

    def test_unavailable_database_has_no_fallback_write(self):
        with patch("database_holdings.request_state",side_effect=self.request):
            book=self.store.load()
        book["account_cash"]=1
        with patch("database_holdings.request_state",side_effect=DatabaseStateError("offline")):
            with self.assertRaises(DatabaseStateError):self.store.save(book)
            with self.assertRaises(DatabaseStateError):self.store.load(force=True)
        self.assertEqual(book["account_cash"],10000)
        self.assertFalse(self.path.exists())

    def test_detached_book_cannot_overwrite_latest_database_state(self):
        with patch("database_holdings.request_state",side_effect=self.request):
            book=self.store.load()
            detached=copy.deepcopy(book)
            detached["account_cash"]=1
            with self.assertRaises(DatabaseStateError):self.store.save(detached)
            self.assertEqual(self.state["holdings"]["account_cash"],10000)

    def test_invalid_trade_preparation_rolls_back_in_memory(self):
        with patch("database_holdings.request_state",side_effect=self.request):
            book=self.store.load()
            book["account_cash"]=1
            with self.assertRaises(ValueError):
                self.store.save(book,records=[{"side":"buy","code":"002841","qty":"invalid"}])
            self.assertEqual(book["account_cash"],10000)
            self.assertEqual(self.state["revision"],1)

    def test_reset_does_not_refresh_over_pending_mutations(self):
        self.state["trades"]=[{"time":"2026-10-14 10:00:00","side":"buy"}]
        with patch("database_holdings.request_state",side_effect=self.request):
            book=self.store.load()
            book["account_cash"]=300000
            self.state["revision"]=2
            self.store._read_at=0
            with self.assertRaises(DatabaseStateError):
                self.store.reset_session_trades("2026-10-14",book,stamp=lambda d:None)
            self.assertEqual(self.state["holdings"]["account_cash"],10000)
            self.assertFalse(self.state["trades"][0].get("reset_archived"))

    def test_reset_archives_history_in_database_and_keeps_delivery_entries(self):
        self.state["trades"]=[{"time":"2026-10-14 10:00:00","side":"buy"}]
        self.state["ledger"]["entries"]=[{"id":"historical"}]
        with patch("database_holdings.request_state",side_effect=self.request):
            book=self.store.load()
            self.assertEqual(self.store.reset_session_trades("2026-10-14",book,stamp=lambda d:None),1)
            self.assertTrue(self.state["trades"][0]["reset_archived"])
            self.assertEqual(len(self.state["ledger"]["entries"]),1)

    def test_production_buy_and_partial_sell_use_database_transaction(self):
        import index
        self.state["holdings"].update(realized_today={},closed_today={},slot_queue={})
        with patch("database_holdings.request_state",side_effect=self.request), \
             patch.object(index,"database_enabled",return_value=True), \
             patch.object(index,"_HOLDINGS_STORE",self.store), \
             patch("wechat_notify.notify_trade_fill"):
            index.apply_paper_slot_buy(code="002841",meta={"name":"Test","market":"SZ"},
                                      price=43.65,qty=100,buy_time="2026-10-14 10:31:00")
            index.apply_exit_fill(code="002841",meta={"name":"Test","market":"SZ"},
                                  fill_px=44,qty=50,cost=43.65,session="2026-10-15",
                                  buy_time="2026-10-14 10:31:00",prev_close=43.65,open_px=44,
                                  px_digits=2,reason="test",trade_note="test",action_kind="half")
            self.assertEqual(self.state["holdings"]["positions"]["002841"]["qty"],50)
            self.assertEqual(self.state["holdings"]["account_cash"],7835)
            self.assertEqual(len(self.state["trades"]),2)
            self.assertEqual(len(self.state["ledger"]["entries"]),2)
            self.assertAlmostEqual(self.state["ledger"]["entries"][1]["pnl"],17.5)
            index.apply_exit_fill(code="002841",meta={"name":"Test","market":"SZ"},
                                  fill_px=44,qty=50,cost=43.65,session="2026-10-15",
                                  buy_time="2026-10-14 10:31:00",prev_close=43.65,open_px=44,
                                  px_digits=2,reason="test",trade_note="test",action_kind="half")
            self.assertEqual(self.state["holdings"]["positions"]["002841"]["qty"],50)
            self.assertEqual(len(self.state["trades"]),2)
            self.assertEqual(self.state["holdings"]["account_cash"],7835)
            self.assertFalse(self.path.exists())


if __name__ == "__main__":unittest.main()
