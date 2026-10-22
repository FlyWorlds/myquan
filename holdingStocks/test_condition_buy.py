"""Condition order replay with an isolated database; never touch production holdings."""
from __future__ import annotations

import contextlib
import copy
import queue
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import index
from condition_buy import ConditionBuyWorker, is_trigger, make_order
from database_holdings import DatabaseHoldingsStore, DatabaseStateError
from quote_feed import QuoteHub

NOW = datetime(2026, 10, 15, 9, 30, 1)


def order(code="000070", **changes):
    result = make_order(code=code, session="2026-10-15", open_px=10., price=10.25, entry_pct=.025,
                        tick=.01, armed_at="2026-10-15 09:25:01", quote_at="2026-10-15 09:25:00",
                        name="Test", market="SZ")
    result.update(changes)
    return result


def quote(**changes):
    result = dict(session="2026-10-15", open=10., high=10.30, low=10., last=10.26,
                  last_ts="2026-10-15 09:30:01", prev_close=10., _quote_source="sina_batch", _open_finalized=True)
    result.update(changes)
    return result


class TestConditionRules(unittest.TestCase):
    def test_five_second_age_boundaries_and_future_source(self):
        self.assertTrue(is_trigger(order(), quote(), NOW, NOW+timedelta(seconds=5)))
        self.assertFalse(is_trigger(order(), quote(), NOW, NOW+timedelta(seconds=5, microseconds=1)))
        later = NOW+timedelta(seconds=5, microseconds=1)
        self.assertFalse(is_trigger(order(), quote(last_ts="2026-10-15 09:30:06"), NOW, later))
        self.assertFalse(is_trigger(order(), quote(last_ts="2026-10-15 09:30:02"), NOW, NOW))

    def test_official_trigger_rounds_up_to_a_valid_tick(self):
        from watch_config import official_buy_trigger
        self.assertEqual(official_buy_trigger(14.83, entry_pct=.025), 15.21)
        custom = order(open=14.83, price=15.21)
        self.assertFalse(is_trigger(custom, quote(open=14.83, low=14.83, high=15.21, last=15.20, prev_close=14.8), NOW, NOW))
        self.assertTrue(is_trigger(custom, quote(open=14.83, low=14.83, high=15.21, last=15.21, prev_close=14.8), NOW, NOW))

    def test_trigger_uses_live_last_not_a_previous_high_and_rejects_bad_ohlc(self):
        self.assertFalse(is_trigger(order(), quote(last=10.24, high=11.), NOW, NOW))
        self.assertFalse(is_trigger(order(), quote(last=10.26, high=10.25), NOW, NOW))
        self.assertFalse(is_trigger(order(), quote(_source_time_verified=False), NOW, NOW))
        self.assertFalse(is_trigger(order(), quote(_reference_only=True), NOW, NOW))
        self.assertFalse(is_trigger(order(), quote(open=10.01), NOW, NOW))

    def test_greater_or_equal_price_triggers(self):
        for price in (10.25, 10.26):
            self.assertTrue(is_trigger(order(), quote(last=price), NOW, NOW))
        self.assertFalse(is_trigger(order(), quote(last=10.24), NOW, NOW))

    def test_no_auction_period_fill(self):
        now = datetime(2026, 10, 15, 9, 25, 3)
        self.assertFalse(is_trigger(order(), quote(last_ts=str(now)), now, now))

    def test_stale_future_old_session_and_unfinalized_quotes_fail_closed(self):
        for changes in ({"last_ts": "2026-10-15 09:29:00"}, {"last_ts": "2026-10-15 09:30:02"},
                        {"session": "2026-10-14"}, {"_open_finalized": False}, {"_quote_source": "seed"},
                        {"open": 9.99}, {"low": 10.26}, {"last": float("nan")}):
            self.assertFalse(is_trigger(order(), quote(**changes), NOW, NOW), changes)

    def test_queued_event_expires_instead_of_backfilling(self):
        self.assertFalse(is_trigger(order(), quote(), NOW - timedelta(seconds=6), NOW))

    def test_restart_does_not_fill_from_the_arming_snapshot(self):
        self.assertFalse(is_trigger(order(armed_at=str(NOW), armed_quote_at=str(NOW)), quote(), NOW, NOW))

    def test_auction_open_requires_pre_bell_arming_and_prompt_observation(self):
        auction = order(kind="auction_open", price=10.)
        self.assertTrue(is_trigger(auction, quote(), NOW, NOW))
        late = NOW + timedelta(seconds=10)
        self.assertFalse(is_trigger(auction, quote(last_ts=str(late)), late, late))
        self.assertFalse(is_trigger(order(kind="auction_open", armed_at=str(NOW)), quote(), NOW, NOW))

    def test_tick_observer_does_no_execution_or_account_work(self):
        execute = Mock()
        worker = ConditionBuyWorker(stop=threading.Event(), execute=execute, log=Mock())
        worker.watch(["sz000070"])
        hub = QuoteHub()
        hub.on_quote = worker.observe
        hub.apply_tick("sz000070", last=10.26, open_px=10., high=10.3, low=10.,
                       prev_close=10., last_ts=str(NOW), source="sina_batch")
        self.assertEqual(worker.events.get_nowait()[0], "sz000070")
        execute.assert_not_called()

    def test_tick_queue_preserves_received_order_not_symbol_order(self):
        worker = ConditionBuyWorker(stop=threading.Event(), execute=Mock(), log=Mock())
        worker.watch(["sz001266", "sz000070"])
        worker.observe("sz001266", quote())
        worker.observe("sz000070", quote())
        self.assertEqual([worker.events.get_nowait()[0], worker.events.get_nowait()[0]], ["sz001266", "sz000070"])

    def test_seed_does_not_send_an_executable_tick(self):
        hub = QuoteHub()
        observer = Mock()
        hub.on_quote = observer
        hub.seed_from_quote("sz000070", quote())
        observer.assert_not_called()

    def test_database_ack_does_not_reset_original_quote_receipt_clock(self):
        worker = ConditionBuyWorker(stop=threading.Event(), execute=Mock(), log=lambda _: None)
        worker.watch(["sz000070"])
        original = NOW - timedelta(seconds=6)
        worker.observe("sz000070", quote(_received_at=original.isoformat(sep=" ")))
        _, snapshot, receipt = worker.events.get_nowait()
        self.assertEqual(receipt, original)
        self.assertFalse(is_trigger(order(), snapshot, receipt, NOW))

    def test_expired_execution_queue_event_does_not_advance_signal_clock(self):
        stop = threading.Event()
        execute = Mock()
        worker = ConditionBuyWorker(stop=stop, execute=execute, log=lambda _: None)
        worker.events.put(("sz000070", quote(), NOW-timedelta(seconds=6)))
        class QueueClock(datetime):
            @classmethod
            def now(cls, tz=None):
                stop.set()
                return NOW
        with patch("condition_buy.datetime", QueueClock):
            worker.run()
        execute.assert_not_called()
        self.assertEqual(worker.expired, 1)
        self.assertIsNone(worker.last_evaluated_at)

    def test_signal_clock_advances_only_when_a_fresh_event_is_evaluated(self):
        stop = threading.Event()
        worker = ConditionBuyWorker(stop=stop, execute=lambda *_: stop.set(), log=lambda _: None)
        worker.events.put(("sz000070", quote(), NOW))
        with patch("condition_buy.datetime", FixedClock):
            worker.run()
        self.assertEqual(worker.last_evaluated_at, str(NOW))
        self.assertEqual(worker.last_source_at, str(NOW))


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


class TestConditionDatabase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "never-write.json"
        self.store = DatabaseHoldingsStore({}, path=lambda: self.path)
        self.state = dict(revision=1, holdings=dict(positions={}, realized_today={}, closed_today={}, slot_queue={},
            account_cash=300000., account_total=300000., condition_buy_orders=dict(session="2026-10-15",
            orders={code: order(code) for code in ("000070", "001266", "002962")}, next_sequence=0)),
            trades=[], ledger={"entries": []})
        stack = self.enterContext(contextlib.ExitStack())
        for name, value in (("_HOLDINGS_STORE", self.store), ("_CONDITION_BUY_ACTIVE", True),
                            ("datetime", FixedClock), ("MAX_NEW_SYMBOLS_PER_SESSION", 2),
                            ("MAX_POSITION_SYMBOLS", 5)):
            stack.enter_context(patch.object(index, name, value))
        stack.enter_context(patch.object(index, "_CONDITION_VERIFIED_IDS", {o["id"] for o in self.state["holdings"]["condition_buy_orders"]["orders"].values()}))
        stack.enter_context(patch.object(index, "database_enabled", return_value=True))
        stack.enter_context(patch.object(index, "trading_session_date", return_value="2026-10-15"))
        stack.enter_context(patch.object(index, "is_signal_window", return_value=True))
        stack.enter_context(patch.object(index, "_now", return_value=str(NOW)))
        stack.enter_context(patch("watch_config.strategy_watchlist_codes", return_value=list(self.state["holdings"]["condition_buy_orders"]["orders"])))
        stack.enter_context(patch("database_holdings.request_state", side_effect=self.request))
        stack.enter_context(patch("wechat_notify.notify_trade_fill"))
        self.feed = Mock()
        self.feed.get_execution_quote = self.feed.get_quote
        self.feed.get_quote.return_value = quote()
        stack.enter_context(patch.object(index, "_watch_feed", self.feed))

    def request(self, method="GET", payload=None, **kwargs):
        if method == "PUT":
            if payload["expectedRevision"] != self.state["revision"]:
                raise DatabaseStateError("conflict")
            self.state = dict(revision=self.state["revision"]+1,
                              **{key: copy.deepcopy(payload[key]) for key in ("holdings", "trades", "ledger")})
        return copy.deepcopy(self.state)

    def trigger(self, code):
        index._execute_condition_quote(code, quote(), NOW)

    def test_fill_at_order_price_and_order_account_delivery_commit_together(self):
        self.trigger("001266")
        self.assertEqual(self.state["revision"], 2)
        trade = self.state["trades"][0]
        self.assertEqual(trade["price"], 10.25)
        self.assertEqual(trade["time"], str(NOW))
        self.assertEqual(trade["signal_time"], str(NOW))
        self.assertEqual(trade["fill_model"], "paper_stop_at_order_price")
        self.assertEqual(self.state["holdings"]["condition_buy_orders"]["orders"]["001266"]["status"], "FILLED")
        self.assertEqual(self.state["ledger"]["entries"][0]["order_id"], trade["order_id"])
        self.assertFalse(self.path.exists())
        self.assertEqual(trade["observed_price"], 10.26)
        self.assertEqual(trade["quote_age_ms"], 0)
        self.assertEqual(self.state["ledger"]["entries"][0]["execution_quote_time"], str(NOW))

    def test_waiting_for_open_settlement_cannot_reuse_a_stale_clock(self):
        clock = [NOW]
        class SlowClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock[0]
        def slow_settle(*_):
            clock[0] = NOW + timedelta(seconds=6)
        with patch.object(index, "datetime", SlowClock), \
             patch.object(index, "_settle_condition_open_protect", side_effect=slow_settle):
            self.trigger("001266")
        self.assertEqual(self.state["trades"], [])

    def test_final_price_check_after_capital_calculation_expires_old_quote(self):
        clock = [NOW]
        class SlowClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock[0]
        original = index.capital_buy_qty
        def slow_calculation(**kwargs):
            clock[0] = NOW + timedelta(seconds=6)
            return original(**kwargs)
        with patch.object(index, "datetime", SlowClock), \
             patch.object(index, "capital_buy_qty", side_effect=slow_calculation):
            self.trigger("001266")
        self.assertEqual(self.state["trades"], [])

    def test_restart_revalidation_requires_a_quote_after_rearming(self):
        index._CONDITION_VERIFIED_IDS.clear()
        draft = order("001266", armed_at=str(NOW), armed_quote_at=str(NOW))
        index._store_condition_drafts([draft], {"001266", "000070", "002962"})
        self.trigger("001266")
        self.assertEqual(self.state["trades"], [])

    def test_gap_above_stop_uses_explicit_paper_fill_price_not_observed_price(self):
        index._execute_condition_quote("001266", quote(last=10.8, high=10.8), NOW)
        trade = self.state["trades"][0]
        self.assertEqual(trade["price"], 10.25)
        self.assertEqual(trade["observed_price"], 10.8)
        self.assertEqual(trade["fill_model"], "paper_stop_at_order_price")

    def test_received_quote_must_commit_before_entering_the_trade_path(self):
        from database_quotes import DatabaseQuotes
        worker = ConditionBuyWorker(stop=threading.Event(), execute=Mock(), log=lambda _: None)
        worker.watch(["sz001266"])
        writer = DatabaseQuotes(stop=threading.Event(), on_committed=worker.observe, log=lambda _: None)
        hub = QuoteHub()
        hub.on_quote = writer.observe
        with patch("quote_feed.datetime", FixedClock):
            hub.apply_tick("sz001266", last=10.26, open_px=10., high=10.3, low=10., prev_close=10.,
                           last_ts=str(NOW), source="sina_batch")
        self.assertTrue(worker.events.empty())
        self.assertEqual(self.state["trades"], [])
        def acknowledge(batch):
            return [dict(item["quote"], _database_quote_symbol=item["symbol"], _database_quote_revision=17)
                    for item in batch]
        with patch("database_quotes.write_quotes", side_effect=acknowledge):
            writer.flush()
        sina, accepted, receipt = worker.events.get_nowait()
        index._execute_condition_quote(sina[-6:], accepted, receipt)
        self.assertEqual(self.state["trades"][0]["quote_db_revision"], 17)
        self.assertEqual(self.state["trades"][0]["price"], 10.25)
        self.assertEqual(self.state["trades"][0]["observed_price"], 10.26)

    def test_duplicate_tick_and_daily_two_symbol_limit(self):
        for code in ("001266", "001266", "000070", "002962"):
            self.trigger(code)
        self.assertEqual([t["code"] for t in self.state["trades"]], ["001266", "000070"])
        self.assertEqual(self.state["holdings"]["condition_buy_orders"]["orders"]["002962"]["reason"], "MAX_NEW_SYMBOLS_PER_SESSION")
        self.assertGreaterEqual(self.state["holdings"]["account_cash"], 0)

    def test_missing_position_mark_blocks_new_buy_without_fake_equity(self):
        self.state["holdings"]["positions"]["600330"] = {"qty": 100, "cost": 10.}
        self.feed.get_quote.return_value = None
        self.trigger("001266")
        self.assertEqual(self.state["trades"], [])
        self.assertEqual(self.state["holdings"]["condition_buy_orders"]["orders"]["001266"]["reason"], "EQUITY_QUOTES_PENDING")

    def test_prior_sell_cannot_be_bypassed(self):
        self.state["holdings"]["realized_today"]["001266"] = {"session": "2026-10-15", "exit_kind": "path"}
        self.trigger("001266")
        self.assertEqual(self.state["trades"], [])
        self.assertEqual(self.state["holdings"]["condition_buy_orders"]["orders"]["001266"]["reason"], "SOLD_TODAY")

    def test_prepare_does_not_replace_triggered_order_or_first_observation(self):
        old = self.state["holdings"]["condition_buy_orders"]["orders"]["001266"]
        old.update(status="TRIGGERED", sequence=1, signal_time=str(NOW))
        index._store_condition_drafts([order("001266", armed_at="2026-10-15 09:29:00")], {"000070", "001266", "002962"})
        kept = self.state["holdings"]["condition_buy_orders"]["orders"]["001266"]
        self.assertEqual(kept["armed_at"], "2026-10-15 09:25:01")
        self.assertEqual(kept["status"], "TRIGGERED")

    def test_database_failure_leaves_no_fill_or_cash_change(self):
        original = copy.deepcopy(self.state)
        def fail(method="GET", payload=None, **kwargs):
            if method == "PUT":
                raise DatabaseStateError("offline")
            return copy.deepcopy(self.state)
        with patch("database_holdings.request_state", side_effect=fail):
            with self.assertRaises(DatabaseStateError):
                self.trigger("001266")
        self.assertEqual(self.state, original)
        self.assertEqual(self.store.cache["data"]["account_cash"], 300000.)

    def test_restored_order_must_be_revalidated_before_filling(self):
        index._CONDITION_VERIFIED_IDS.clear()
        self.trigger("001266")
        self.assertEqual(self.state["trades"], [])
        index._store_condition_drafts([order("001266")], {"001266", "000070", "002962"})
        self.trigger("001266")
        self.assertEqual(len(self.state["trades"]), 1)

    def seed_overnight(self):
        self.state["holdings"]["positions"]["000070"] = dict(qty=900, available=900, cost=10.,
            buy_time="2026-10-14 10:00:00", peak_high=10., name="Test", market="SZ")

    def test_quote_half_full_cash_quantities_and_delivery_are_consistent(self):
        self.seed_overnight()
        index._execute_quote_exit("000070", quote(last=11., high=11.), NOW)
        self.assertEqual(self.state["holdings"]["positions"]["000070"]["qty"], 500)
        self.assertEqual(self.state["holdings"]["account_cash"], 304392.98)
        index._execute_quote_exit("000070", quote(last=11., high=11.), NOW)
        self.assertEqual(len(self.state["trades"]), 1)
        index._execute_quote_exit("000070", quote(last=10.7, high=11.), NOW)
        self.assertEqual(self.state["holdings"]["positions"]["000070"]["qty"], 0)
        self.assertEqual(self.state["holdings"]["account_cash"], 309734.44)
        self.assertEqual([t["qty"] for t in self.state["trades"]], [400, 500])
        self.assertEqual(len(self.state["ledger"]["entries"]), 2)
        self.assertEqual(self.state["trades"][-1]["fill_model"], "factor26_observed_quote")

    def test_quote_exit_database_failure_rolls_back_peak_position_and_cash(self):
        self.seed_overnight()
        initial = copy.deepcopy(self.state)
        def fail(method="GET", payload=None, **kwargs):
            if method == "PUT":
                raise DatabaseStateError("offline")
            return copy.deepcopy(self.state)
        with patch("database_holdings.request_state", side_effect=fail):
            with self.assertRaises(DatabaseStateError):
                index._execute_quote_exit("000070", quote(last=11., high=11.), NOW)
        self.assertEqual(self.state, initial)

    def test_open_exit_then_buy_keeps_order_on_the_new_database_state(self):
        self.seed_overnight()
        self.state["holdings"]["positions"]["000070"]["stop_noted"] = True
        self.feed.get_quote.side_effect = lambda sina: quote(open=9.5, last=9.5, high=9.5, low=9.5) if sina == "sz000070" else quote()
        self.trigger("001266")
        self.assertEqual([t["side"] for t in self.state["trades"]], ["sell", "buy"])
        self.assertEqual(self.state["holdings"]["condition_buy_orders"]["orders"]["001266"]["status"], "FILLED")
        self.assertEqual(self.state["holdings"]["positions"]["000070"]["qty"], 0)

    def test_exit_time_is_decision_time_not_an_older_source_timestamp(self):
        self.seed_overnight()
        index._execute_quote_exit("000070", quote(last=11., high=11., last_ts="2026-10-15 09:30:00"), NOW)
        trade = self.state["trades"][0]
        self.assertEqual(trade["signal_time"], "2026-10-15 09:30:00")
        self.assertEqual(trade["time"], str(NOW))

    def test_changed_daily_evidence_blocks_a_prepared_order(self):
        self.state["holdings"]["condition_buy_orders"]["orders"]["001266"]["daily_sig"] = "frozen-reference"
        with patch.object(index, "_DAILY_CACHE", {}):
            self.trigger("001266")
        self.assertEqual(self.state["trades"], [])
        self.assertEqual(self.state["holdings"]["condition_buy_orders"]["orders"]["001266"]["reason"], "REFERENCE_DATA_CHANGED")

    def test_new_near_limit_audit_can_block_an_existing_armed_order(self):
        index._store_condition_drafts([order("001266", status="BLOCKED", reason="AUCTION_NEAR_LIMIT_UP")],
                                      {"001266", "000070", "002962"})
        self.trigger("001266")
        self.assertEqual(self.state["trades"], [])
        self.assertEqual(self.state["holdings"]["condition_buy_orders"]["orders"]["001266"]["status"], "BLOCKED")

    def test_readonly_quote_rows_do_not_pull_or_replay_minutes(self):
        self.seed_overnight()
        item = dict(code="000070", sina="sz000070", name="Test", market="SZ", pct=.025)
        with patch.object(index, "_scan_watchlist", return_value=[item]), \
                patch("strategy_simulator.snapshot_books", return_value={}), \
                patch.object(index, "_today_1m_bars", side_effect=AssertionError("minute IO")), \
                patch.object(index, "_m1_lookback_bars", side_effect=AssertionError("minute replay")), \
                patch.object(index, "_watch_daily", side_effect=AssertionError("daily IO")), \
                patch.object(index, "_calendar_signal_session", return_value="2026-10-15"):
            rows = index._collect_quote_runtime_rows(get_quote=lambda _: quote())
        self.assertEqual(rows[0]["持仓"], 900)
        self.assertEqual(rows[0]["现价"], 10.26)
        self.assertEqual(self.state["revision"], 1)
        self.assertNotIn("策略收益%", rows[0])

