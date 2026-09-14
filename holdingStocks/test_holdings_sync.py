"""Win/Mac 账本缓存：holdings_watch.json 不得盖过更新的 holdings.json。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from holdings_sync import snapshot_cache_stale


class SnapshotCacheTests(unittest.TestCase):
    def test_stale_when_holdings_newer(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            watch = tmp / "holdings_watch.json"
            holdings = tmp / "holdings.json"
            watch.write_text("{}", encoding="utf-8")
            holdings.write_text('{"updated_at":"later"}', encoding="utf-8")
            os.utime(watch, (1_700_000_000, 1_700_000_000))
            os.utime(holdings, (1_700_000_100, 1_700_000_100))
            self.assertTrue(snapshot_cache_stale(watch, holdings))

    def test_fresh_when_watch_newer(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            holdings = tmp / "holdings.json"
            watch = tmp / "holdings_watch.json"
            holdings.write_text("{}", encoding="utf-8")
            watch.write_text(json.dumps({"type": "snapshot"}), encoding="utf-8")
            os.utime(holdings, (1_700_000_000, 1_700_000_000))
            os.utime(watch, (1_700_000_100, 1_700_000_100))
            self.assertFalse(snapshot_cache_stale(watch, holdings))

    def test_stale_if_watch_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            holdings = tmp / "holdings.json"
            holdings.write_text("{}", encoding="utf-8")
            self.assertTrue(snapshot_cache_stale(tmp / "missing.json", holdings))


if __name__ == "__main__":
    unittest.main()
