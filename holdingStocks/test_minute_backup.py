"""Research backup tests use temporary SQLite and mocked subprocesses, never live accounts."""
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from minute_backup import MinuteBackup, archive, validated_bars

NOW = datetime(2026, 10, 15, 10, 0, 30)


def bar(at="2026-10-15 09:58:00", **changes):
    return dict(day=at, open="10", high="11", low="9", close="10.5", volume="100", **changes)


class TestMinuteBackup(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "research.sqlite3"
        self.ready, self.stop = threading.Event(), threading.Event()
        self.backup = MinuteBackup(stop=self.stop, rendered=self.ready,
            symbols=lambda: ["sz000070", "sz000070", "sh600330"], path=self.path, log=lambda _: None)

    def test_waits_for_render_and_pauses_opening(self):
        with patch("minute_backup.subprocess.run") as run:
            self.assertFalse(self.backup.run_once(NOW))
            self.ready.set()
            for clock in ("09:15", "09:25", "09:35", "09:39"):
                self.assertFalse(self.backup.run_once(datetime.fromisoformat("2026-10-15 " + clock)))
            run.assert_not_called()
            self.assertTrue(self.backup.run_once(NOW))
            self.assertEqual(run.call_args.kwargs["timeout"], 20)
            self.assertEqual(run.call_args.args[0][-2], "sz000070")

    def test_priority_ttl_and_stop(self):
        self.ready.set()
        with patch("minute_backup.subprocess.run") as run:
            self.assertTrue(self.backup.run_once(NOW))
            self.assertTrue(self.backup.run_once(NOW))
            self.assertFalse(self.backup.run_once(NOW))
            self.assertEqual([c.args[0][-2] for c in run.call_args_list], ["sz000070", "sh600330"])
            self.stop.set()
            self.assertFalse(self.backup.run_once(NOW))

    def test_timeout_backoff_does_not_block_next_symbol(self):
        self.ready.set()
        with patch("minute_backup.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 20)) as run:
            self.assertTrue(self.backup.run_once(NOW))
            self.assertTrue(self.backup.run_once(NOW))
            self.assertFalse(self.backup.run_once(NOW))
            self.assertEqual(run.call_count, 2)

    def test_completed_bars_only_and_validation(self):
        rows = [bar(), bar("2026-10-15 09:59:00"), bar("2026-10-15 10:00:00"),
                bar("2026-10-15 10:01:00"), bar("2026-10-15 12:00:00")]
        result = validated_bars(rows, NOW)
        self.assertEqual([r[0] for r in result], ["2026-10-15 09:58:00", "2026-10-15 09:59:00"])
        invalid = bar()
        invalid["high"] = "9"
        with self.assertRaises(ValueError):
            validated_bars([invalid], NOW)
        invalid["high"] = "nan"
        with self.assertRaises(ValueError):
            validated_bars([invalid], NOW)

    def test_archive_is_idempotent_and_retains_older_bars(self):
        archive("sz000070", self.path, now=NOW, raw=[bar("2026-10-14 09:58:00"), bar()])
        archive("sz000070", self.path, now=NOW, raw=[bar()])
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM research_minutes").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT source FROM research_fetches").fetchone()[0], "sina_1m_unadjusted")
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(tables, {"research_minutes", "research_fetches"})
        with self.assertRaises(ValueError):
            archive("../bad", self.path, now=NOW, raw=[bar()])
        with self.assertRaises(ValueError):
            archive("sz000070", self.path, now=NOW, raw=[])
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM research_minutes").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
