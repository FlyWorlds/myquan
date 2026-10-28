import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from database_strategy_books import StrategyBooksClient, StrategyDatabaseError, apply_database_book_to_row
from strategy_books_runtime import StrategyBooksRuntime
from test_condition_buy import order, quote

NOW = datetime(2026, 10, 15, 10, 0)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


class TestStrategyBooksClient(unittest.TestCase):
    def test_default_book_namespace_is_strategy1(self):
        self.assertEqual(StrategyBooksClient().strategy_id, "strategy1")

    def test_requests_to_two_strategies_have_distinct_idempotency_keys(self):
        with patch("database_strategy_books.request_books", return_value=dict(symbol="000070", revision=1)) as request:
            for sid in ("strategy1", "strategy16"):
                StrategyBooksClient(strategy_id=sid).command("000070", {}, quote=quote(last_ts=str(NOW)), now=NOW)
        calls = request.call_args_list
        self.assertNotEqual(calls[0].args[1]["requestId"], calls[1].args[1]["requestId"])
        self.assertEqual(calls[0].kwargs["strategy_id"], "strategy1")
        self.assertEqual(calls[1].kwargs["strategy_id"], "strategy16")

    def test_strategy1_row_is_not_labelled_as_strategy16_book(self):
        from watch_snapshot import _strip_holdings_pnl
        row = {}
        apply_database_book_to_row(row, dict(strategy_id="strategy1",revision=1))
        self.assertEqual(_strip_holdings_pnl(row)["收益账本"], "strategy1_database")

    def test_cache_is_updated_only_after_database_acknowledges(self):
        client = StrategyBooksClient()
        committed = dict(symbol="000070", revision=1, virtual_cash=100000, virtual_shares=0)
        with patch("database_strategy_books.request_books", return_value=committed):
            client.command("000070", {}, quote=quote(last_ts=str(NOW)), now=NOW)
        self.assertEqual(client.snapshot()["000070"], committed)
        with patch("database_strategy_books.request_books", side_effect=StrategyDatabaseError("offline")):
            with self.assertRaises(StrategyDatabaseError):
                client.command("000070", committed, quote=quote(last_ts=str(NOW)), now=NOW, side="BUY", price=10., qty=100)
        self.assertEqual(client.snapshot()["000070"], committed)

    def test_slow_refresh_cannot_replace_a_newer_committed_book(self):
        client = StrategyBooksClient()
        client._books = {"000070": dict(revision=3, virtual_cash=90000)}
        with patch("database_strategy_books.request_books", return_value={"000070": dict(revision=2, virtual_cash=100000)}):
            client.refresh()
        self.assertEqual(client.snapshot()["000070"]["revision"], 3)

    def test_strategy_tab_uses_strategy_cycle_not_paper_trade(self):
        from watch_snapshot import _strip_holdings_pnl
        book = dict(revision=3, state="LONG", initial_cash=100000, virtual_cash=94400,
            virtual_shares=600, entry_price=10, last_mark=12, single_cost_base=10000,
            single_realized_pnl=400, single_sold_shares=400, total_pnl=1600, cycle_pnl=1600,
            cumulative_return_pct=1.6, cycle_return_pct=16., single_return_pct=20.,
            unrealized_pnl=1200, history_status="legacy_checkpoint_unverified")
        row = {"综合单笔收入%": 14.99}
        apply_database_book_to_row(row, book)
        strategy = _strip_holdings_pnl(row)
        self.assertEqual(strategy["综合单笔收入%"], 16.)
        self.assertEqual(strategy["单笔收入%"], 20.)
        self.assertEqual(strategy["综合策略收益%"], 1.6)
        self.assertEqual(row["综合单笔收入%"], 14.99)
        self.assertEqual(strategy["收益账本"], "strategy16_database")


class TestStrategyRuntime(unittest.TestCase):
    def setUp(self):
        self.client = StrategyBooksClient()
        self.client.ready = True
        self.client.command = Mock()
        self.runtime = StrategyBooksRuntime(self.client, vol_for=lambda *_: None, signal_window=lambda _: True)
        self.enterContext(patch("strategy_books_runtime.datetime", Clock))

    def test_pool_strategy_buys_independently_of_two_paper_slots(self):
        codes = {"000070", "001266", "002962", "600330"}
        self.runtime.prepare([order(code) for code in codes], codes)
        for code in codes:
            self.runtime.on_quote(("sh" if code.startswith("6") else "sz")+code, quote(last_ts=str(NOW)), NOW)
        self.assertEqual(self.client.command.call_count, 4)
        for call in self.client.command.call_args_list:
            self.assertEqual(call.kwargs["side"], "BUY")
            self.assertEqual(call.kwargs["qty"], 9200)

    def test_prearmed_auction_order_survives_breakout_refresh_at_the_bell(self):
        class BellClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 10, 15, 9, 30, 1)
        self.runtime.prepare([order(kind="auction_open", price=10.)], {"000070"})
        with patch("strategy_books_runtime.datetime", BellClock):
            self.runtime.prepare([order(armed_at="2026-10-15 09:30:01")], {"000070"})
        self.assertEqual(self.runtime.orders["000070"]["kind"], "auction_open")
        self.assertEqual(self.runtime.orders["000070"]["price"], 10.)
        self.runtime.prepare([order(status="BLOCKED")], {"000070"})
        self.assertEqual(self.runtime.orders["000070"]["status"], "BLOCKED")

    def test_book_sells_partial_quantity_and_does_not_touch_paper(self):
        self.client._books = {"000070": dict(revision=1, virtual_shares=900, virtual_cash=91000,
            entry_price=10., entry_time="2026-10-14 10:00:00", peak_high=10., tp_stage=0)}
        self.runtime.prepare([], {"000070"})
        self.runtime.on_quote("sz000070", quote(last=11., high=11., last_ts=str(NOW)), NOW)
        self.assertEqual(self.client.command.call_args.kwargs["side"], "SELL")
        self.assertEqual(self.client.command.call_args.kwargs["qty"], 400)

    def test_failed_or_unready_database_does_not_fallback_to_local_books(self):
        self.client.ready = False
        self.runtime.prepare([order()], {"000070"})
        self.runtime.on_quote("sz000070", quote(last_ts=str(NOW)), NOW)
        self.client.command.assert_not_called()

    def test_peak_and_t1_note_changes_are_not_lost_to_mark_throttle(self):
        self.client._books = {"000070": dict(revision=1, virtual_shares=900, virtual_cash=91000,
            entry_price=10., entry_time="2026-10-15 09:31:00", peak_high=10., last_mark=10.,
            quote_exit_session="2026-10-15", quote_session_peak=10., available=0, quote_cycle_low=10.)}
        self.runtime.prepare([], {"000070"})
        self.runtime.last_write["000070"] = 99.5
        with patch("strategy_books_runtime.time.monotonic", return_value=100.):
            self.runtime.on_quote("sz000070", quote(last=10.5, high=10.5, last_ts=str(NOW)), NOW)
        self.assertEqual(self.client.command.call_count, 1)
        self.assertEqual(self.client.command.call_args.kwargs["state"]["peak_high"], 10.5)

    def test_pure_mark_updates_remain_throttled(self):
        self.client._books = {"000070": dict(revision=1, virtual_shares=0, virtual_cash=100000,
            last_mark=10., last_quote_ts="2026-10-15 09:59:59")}
        self.runtime.prepare([], {"000070"})
        self.runtime.last_write["000070"] = 99.5
        with patch("strategy_books_runtime.time.monotonic", return_value=100.):
            self.runtime.on_quote("sz000070", quote(last=10.5, high=10.5, last_ts=str(NOW)), NOW)
        self.client.command.assert_not_called()

    def test_previous_official_close_can_value_but_never_trade_or_raise_peaks(self):
        self.runtime.signal_window = lambda _: False
        self.runtime.prepare([], {"000070"})
        self.client._books = {"000070": dict(revision=1, virtual_shares=900, entry_price=10.,
            entry_time="2026-10-13 09:31:00", peak_high=10., last_mark=10.)}
        self.runtime.on_quote("sz000070", quote(last=11., high=11., last_ts="2026-10-14 15:00:00", session="2026-10-14"), NOW)
        self.client.command.assert_called_once()
        self.assertNotIn("side", self.client.command.call_args.kwargs)
        self.assertNotIn("state", self.client.command.call_args.kwargs)

    def test_stale_close_during_live_session_cannot_be_a_fill_or_mark(self):
        self.runtime.prepare([], {"000070"})
        self.runtime.on_quote("sz000070", quote(last=11., high=11., last_ts="2026-10-14 15:00:00", session="2026-10-14"), NOW)
        self.client.command.assert_not_called()

    def test_peak_survives_a_second_quote_inside_the_same_write_second(self):
        self.client._books = {"000070": dict(revision=1, virtual_shares=900, virtual_cash=91000,
            entry_price=10., entry_time="2026-10-15 09:31:00", peak_high=10., last_mark=10.,
            quote_exit_session="2026-10-15", quote_session_peak=10., available=0, quote_cycle_low=10.)}
        def acknowledge(code, book, **command):
            committed = dict(book, **command["state"])
            committed.update(revision=book["revision"] + 1, last_mark=command["quote"]["last"],
                             last_quote_ts=command["quote"]["last_ts"])
            self.client._books[code] = committed
        self.client.command.side_effect = acknowledge
        self.runtime.prepare([], {"000070"})
        self.runtime.last_write["000070"] = 99.5
        with patch("strategy_books_runtime.time.monotonic", return_value=100.):
            self.runtime.on_quote("sz000070", quote(last=10.5, high=10.5, last_ts=str(NOW)), NOW)
            self.runtime.on_quote("sz000070", quote(last=10.4, high=10.5, last_ts=str(NOW)), NOW)
        self.assertEqual(self.client.get("000070")["peak_high"], 10.5)
        self.assertEqual(self.client.command.call_count, 1)

    def test_changed_reference_and_same_day_exit_block_strategy_rebuy(self):
        self.runtime.prepare([order()], {"000070"})
        self.runtime.order_valid = lambda _: False
        self.runtime.on_quote("sz000070", quote(last_ts=str(NOW)), NOW)
        self.assertTrue(all(c.kwargs.get("side", "MARK") == "MARK" for c in self.client.command.call_args_list))
        self.client.command.reset_mock()
        self.runtime.order_valid = lambda _: True
        self.client._books = {"000070": dict(revision=2, virtual_shares=0, virtual_cash=100000,
            exit_time="2026-10-15 09:31:00", last_mark=10.26, last_quote_ts=str(NOW))}
        self.runtime.on_quote("sz000070", quote(last_ts=str(NOW)), NOW)
        self.client.command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
