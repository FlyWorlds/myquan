import copy
import threading
import unittest
from unittest.mock import Mock, patch

from database_quotes import DatabaseQuotes
from test_condition_buy import quote


def committed(batch):
    result = []
    for revision, item in enumerate(batch, 1):
        result.append(dict(item["quote"], _database_quote_revision=revision,
                           _database_quote_symbol=item["symbol"]))
    return result


class TestDatabaseQuotes(unittest.TestCase):
    def setUp(self):
        self.consume = Mock()
        self.client = DatabaseQuotes(stop=threading.Event(), on_committed=self.consume, log=lambda _: None)

    def observe(self, **changes):
        value = quote(_source_time_verified=True, _received_at="2026-10-15 09:30:01.123456", **changes)
        self.client.observe("sz000070", value)

    def test_repeated_tick_is_deduplicated_but_same_second_peak_is_preserved(self):
        self.observe()
        self.observe()
        self.observe(last=10.8, high=10.8)
        self.assertEqual(self.client.events.qsize(), 2)
        self.assertEqual(self.client.duplicates, 1)

    def test_failed_database_write_allows_same_tick_to_retry(self):
        self.observe()
        with patch("database_quotes.write_quotes", side_effect=OSError("offline")):
            self.client.flush()
        self.observe()
        self.assertEqual(self.client.events.qsize(), 1)

    def test_writer_wakes_on_observation_instead_of_polling(self):
        waiting, committed_event = threading.Event(), threading.Event()
        event = threading.Event()
        class TrackedWake:
            def wait(self, timeout=None):
                waiting.set()
                return event.wait(timeout)
            def set(self): event.set()
            def clear(self): event.clear()
        self.client._wake = TrackedWake()
        self.client.on_committed = lambda *_: committed_event.set()
        with patch("database_quotes.write_quotes", side_effect=committed):
            worker = threading.Thread(target=self.client.run, daemon=True)
            worker.start()
            try:
                self.assertTrue(waiting.wait(1))
                self.observe()
                self.assertTrue(committed_event.wait(.5))
            finally:
                self.client.stop.set(); event.set(); worker.join(1)
        self.assertFalse(worker.is_alive())

    def test_tencent_fallback_requires_the_same_database_ack(self):
        self.observe(_quote_source="tencent_batch")
        self.consume.assert_not_called()
        with patch("database_quotes.write_quotes", side_effect=committed):
            self.client.flush()
        self.consume.assert_called_once()

    def test_no_execution_before_database_ack_and_no_fallback_when_offline(self):
        self.observe()
        self.consume.assert_not_called()
        with patch("database_quotes.write_quotes", side_effect=OSError("offline")):
            self.client.flush()
        self.consume.assert_not_called()
        self.assertIsNone(self.client.get("sz000070"))
        self.assertIsNotNone(self.client.error)

    def test_same_symbol_peak_and_reversal_are_not_coalesced_away(self):
        self.observe(last=10.5, high=10.5)
        self.observe(last=10.4, high=10.5)
        with patch("database_quotes.write_quotes", side_effect=committed):
            self.client.flush()
        self.assertEqual([c.args[1]["last"] for c in self.consume.call_args_list], [10.5, 10.4])
        self.assertEqual(self.client.get("sz000070")["last"], 10.4)
        self.assertTrue(self.client.ready)

    def test_seed_and_unverified_clock_never_enter_database_execution_queue(self):
        self.client.observe("sz000070", quote(_source_time_verified=False))
        self.assertTrue(self.client.events.empty())

    def test_database_backlog_discards_expired_events_instead_of_starving_new_quotes(self):
        with patch("database_quotes.time.monotonic", return_value=0):
            self.observe()
        with patch("database_quotes.time.monotonic", return_value=6), \
             patch("database_quotes.write_quotes") as write:
            self.client.flush()
        write.assert_not_called()
        self.assertEqual(self.client.expired, 1)

    def test_invalid_symbol_prices_do_not_poison_the_whole_batch(self):
        self.observe(prev_close=0)
        self.assertTrue(self.client.events.empty())
        self.assertEqual(self.client.rejected, 1)

    def test_invalid_batch_ack_is_not_partially_dispatched(self):
        self.observe()
        self.observe()
        def malformed(batch):
            result = committed(batch)
            result[1]["_database_quote_symbol"] = "sh600330"
            return result
        with patch("database_quotes.write_quotes", side_effect=malformed):
            self.client.flush()
        self.consume.assert_not_called()
        self.assertIsNone(self.client.get("sz000070"))

    def test_duplicate_database_revision_does_not_trigger_again(self):
        self.observe()
        saved = None
        def save(batch):
            nonlocal saved
            if saved is None:
                saved = committed(batch)
            return copy.deepcopy(saved)
        with patch("database_quotes.write_quotes", side_effect=save):
            self.client.flush()
            self.observe()
            self.client.flush()
        self.assertEqual(self.consume.call_count, 1)

    def test_startup_database_reference_is_not_a_new_trigger(self):
        reference = dict(quote(), _source_time_verified=True, _database_quote_symbol="sz000070",
                         _database_quote_revision=3)
        with patch("database_quotes.read_quotes", return_value={"sz000070": reference}):
            self.client.refresh()
        self.assertEqual(self.client.get("sz000070")["_database_quote_revision"], 3)
        self.assertIsNone(self.client.get("sz000070", executable=True))
        self.consume.assert_not_called()
        self.assertIsNone(self.client.latest_quote_at)

    def test_slow_reference_read_cannot_replace_newer_acknowledgement(self):
        older = dict(quote(last=10.25), _source_time_verified=True, _database_quote_symbol="sz000070",
                     _database_quote_revision=2)
        newer = dict(older, last=10.26, _database_quote_revision=3)
        def delayed_read():
            self.client._quotes["sz000070"] = newer
            return {"sz000070": older}
        with patch("database_quotes.read_quotes", side_effect=delayed_read):
            self.client.refresh()
        self.assertEqual(self.client.get("sz000070")["last"], 10.26)
        self.consume.assert_not_called()

    def test_failed_reference_read_does_not_mask_write_failure(self):
        self.client.error = "write failed"
        with patch("database_quotes.read_quotes", side_effect=OSError("read failed")):
            self.client.refresh()
        self.assertEqual(self.client.error, "write failed")
        self.assertIsNotNone(self.client.read_error)

    def test_new_acknowledged_observation_can_replace_a_reference_without_replaying_it(self):
        reference = dict(quote(), _source_time_verified=True, _database_quote_symbol="sz000070",
                         _database_quote_revision=3)
        with patch("database_quotes.read_quotes", return_value={"sz000070": reference}):
            self.client.refresh()
        self.client.observe("sz000070", quote(last_ts="2026-10-15 09:30:02", _source_time_verified=True,
            _received_at="2026-10-15 09:30:02.123456"))
        def acknowledged(batch):
            return [dict(item["quote"], _database_quote_revision=4, _database_quote_symbol=item["symbol"])
                    for item in batch]
        with patch("database_quotes.write_quotes", side_effect=acknowledged):
            self.client.flush()
        self.assertFalse(self.client.get("sz000070", executable=True)["_reference_only"])
        self.consume.assert_called_once()

    def test_same_version_is_usable_only_after_actual_network_observation_and_ack(self):
        reference = dict(quote(), _received_at="2026-10-15 09:30:01.123456", _source_time_verified=True,
                         _database_quote_symbol="sz000070", _database_quote_revision=3)
        with patch("database_quotes.read_quotes", return_value={"sz000070": reference}):
            self.client.refresh()
        self.consume.assert_not_called()
        self.observe()
        with patch("database_quotes.write_quotes", return_value=[reference]):
            self.client.flush()
        self.consume.assert_called_once()
        self.assertEqual(self.client.get("sz000070", executable=True)["_received_at"], reference["_received_at"])

    def test_newer_shared_database_quote_is_reference_not_locally_received_trigger(self):
        newer = dict(quote(last=10.8, high=10.8, last_ts="2026-10-15 09:30:02"),
            _received_at="2026-10-15 09:30:02.123456", _source_time_verified=True,
            _database_quote_symbol="sz000070", _database_quote_revision=4)
        self.observe()
        with patch("database_quotes.write_quotes", return_value=[newer]):
            self.client.flush()
        self.assertEqual(self.client.get("sz000070")["last"], 10.8)
        self.assertIsNone(self.client.get("sz000070", executable=True))
        self.consume.assert_not_called()


if __name__ == "__main__":
    unittest.main()
