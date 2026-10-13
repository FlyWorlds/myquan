from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import index
import start_watch


class WatchRemoteLedgerTests(unittest.TestCase):
    def _install_fake_holdings_sync(self, result: str = "pulled") -> list[dict[str, object]]:
        calls: list[dict[str, object]] = []

        def pull_holdings(*, force: bool = False, quiet: bool = False) -> str:
            calls.append({"force": force, "quiet": quiet})
            return result

        self._old_holdings_sync = sys.modules.get("holdings_sync")
        sys.modules["holdings_sync"] = types.SimpleNamespace(pull_holdings=pull_holdings)
        self.addCleanup(self._restore_holdings_sync)
        return calls

    def _restore_holdings_sync(self) -> None:
        old = getattr(self, "_old_holdings_sync", None)
        if old is None:
            sys.modules.pop("holdings_sync", None)
        else:
            sys.modules["holdings_sync"] = old

    def test_start_watch_forces_remote_ledger(self) -> None:
        calls = self._install_fake_holdings_sync("pulled")

        start_watch._pull_remote_holdings_for_watch()

        self.assertEqual(calls, [{"force": True, "quiet": False}])

    def test_start_watch_stops_when_remote_missing(self) -> None:
        self._install_fake_holdings_sync("missing-remote")

        with self.assertRaises(SystemExit):
            start_watch._pull_remote_holdings_for_watch()

    def test_index_watch_forces_remote_ledger(self) -> None:
        calls = self._install_fake_holdings_sync("pulled")

        index._pull_remote_holdings_for_watch()

        self.assertEqual(calls, [{"force": True, "quiet": False}])

    def test_index_watch_stops_when_remote_missing(self) -> None:
        self._install_fake_holdings_sync("missing-remote")

        with self.assertRaises(SystemExit):
            index._pull_remote_holdings_for_watch()


if __name__ == "__main__":
    unittest.main()
