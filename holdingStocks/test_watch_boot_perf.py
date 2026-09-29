# -*- coding: utf-8 -*-
"""盯盘冷启动性能回归：账本↔盯盘名单不得互相递归；thr 表按 mtime 缓存；分层扫描。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = Path(__file__).resolve().parent
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

import index  # noqa: E402
from strategy import watch_universe  # noqa: E402


class TestLoadHoldingsNoRecursion(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "holdings.json"
        self.path.write_text(
            json.dumps({"positions": {}, "realized_today": {}}), encoding="utf-8"
        )
        self._saved_cache = dict(index._HOLDINGS_CACHE)
        index._HOLDINGS_CACHE.clear()
        index._HOLDINGS_CACHE.update({"data": None, "mtime": 0.0})

    def tearDown(self) -> None:
        index._HOLDINGS_CACHE.clear()
        index._HOLDINGS_CACHE.update(self._saved_cache)
        self._tmp.cleanup()

    def test_cold_load_calls_itself_once(self) -> None:
        real = index.load_holdings
        with mock.patch.object(index, "HOLDINGS_FILE", self.path), mock.patch.object(
            index, "load_holdings", wraps=real
        ) as spy:
            t0 = time.perf_counter()
            data = index.load_holdings()
            elapsed = time.perf_counter() - t0
        self.assertEqual(spy.call_count, 1, "load_holdings 被 watchlist 回调（递归）")
        self.assertLess(elapsed, 5.0)
        self.assertTrue(data["positions"], "应为盯盘宇宙补齐空仓位")


class TestThrMapCache(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "thr.json"
        self._write({"600552": {"thr": 0.025}})
        self._saved = dict(watch_universe._THR_MAP_CACHE)
        watch_universe._THR_MAP_CACHE.update({"mtime": None, "data": {}})

    def tearDown(self) -> None:
        watch_universe._THR_MAP_CACHE.clear()
        watch_universe._THR_MAP_CACHE.update(self._saved)
        self._tmp.cleanup()

    def _write(self, thrs: dict) -> None:
        self.path.write_text(json.dumps({"thrs": thrs}), encoding="utf-8")

    def test_cached_copy_and_reload_on_mtime(self) -> None:
        with mock.patch.object(watch_universe, "STRATEGY16_THR_PATH", self.path):
            first = watch_universe.load_strategy16_thr_map()
            self.assertAlmostEqual(first["600552"], 0.025)
            first["600552"] = 9.9
            with mock.patch.object(
                watch_universe, "_read_strategy16_thr_map", side_effect=AssertionError
            ):
                again = watch_universe.load_strategy16_thr_map()
            self.assertAlmostEqual(again["600552"], 0.025, msg="调用方改动不得污染缓存")

            self._write({"600552": {"thr": 0.03}})
            st = self.path.stat()
            os.utime(self.path, (st.st_atime, st.st_mtime + 10))
            self.assertAlmostEqual(
                watch_universe.load_strategy16_thr_map()["600552"], 0.03
            )

    def test_missing_file_empty(self) -> None:
        with mock.patch.object(
            watch_universe, "STRATEGY16_THR_PATH", self.path.with_name("nope.json")
        ):
            self.assertEqual(watch_universe.load_strategy16_thr_map(), {})


class TestBootPrimaryOnlyScan(unittest.TestCase):
    def tearDown(self) -> None:
        index._set_watch_boot_primary_only(False)

    def test_primary_only_then_full(self) -> None:
        holdings = {"positions": {}}
        full = index._scan_watchlist(holdings)
        primary = index.primary_watchlist(holdings)
        index._set_watch_boot_primary_only(True)
        boot = index._scan_watchlist(holdings)
        self.assertEqual([w["code"] for w in boot], [w["code"] for w in primary])
        self.assertEqual(len(index._scan_watchlist(holdings, full=True)), len(full))
        index._set_watch_boot_primary_only(False)
        self.assertEqual(len(index._scan_watchlist(holdings)), len(full))


if __name__ == "__main__":
    unittest.main()
