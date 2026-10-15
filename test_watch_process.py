"""Process queries must not delete the real watch lock or stop listeners."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_HS = Path(__file__).resolve().parent / "holdingStocks"
if str(_HS) not in sys.path:
    sys.path.insert(0, str(_HS))

from watch_process import (  # noqa: E402
    clear_lock,
    describe_listeners,
    read_lock,
)


class WatchProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pid_file = Path(self.tmp.name) / "holdings_watch.pid"
        patcher = mock.patch("watch_process.PID_FILE", self.pid_file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_clear_stale_lock(self) -> None:
        pid_file = self.pid_file
        if pid_file.exists():
            pid_file.unlink()
        pid_file.write_text('{"pid": 999999999}', encoding="utf-8")
        self.assertTrue(clear_lock(only_if_stale=True))
        self.assertFalse(pid_file.exists())

    def test_listener_description_is_read_only(self) -> None:
        with mock.patch("watch_process.find_listeners",return_value=[123]):
            self.assertEqual(describe_listeners("127.0.0.1",[8765]),{8765:[123]})

    def test_read_lock_missing(self) -> None:
        pid_file = self.pid_file
        if pid_file.exists():
            pid_file.unlink()
        self.assertIsNone(read_lock())

    def test_win_listeners_parses_netstat(self) -> None:
        from watch_process import _win_listeners

        sample = """
  TCP    127.0.0.1:8765         0.0.0.0:0              LISTENING       4242
  TCP    127.0.0.1:3000         0.0.0.0:0              LISTENING       5252
"""
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=sample)
            pids = _win_listeners(8765)
        self.assertEqual(pids, [4242])


if __name__ == "__main__":
    unittest.main()
