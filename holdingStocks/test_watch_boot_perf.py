# -*- coding: utf-8 -*-
"""盯盘冷启动性能回归：账本↔盯盘名单不得互相递归；thr 表按 mtime 缓存；分层扫描。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
import threading
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
        import stock_names

        real = index.load_holdings
        with mock.patch.object(index, "HOLDINGS_FILE", self.path), mock.patch.object(
            index, "load_holdings", wraps=real
        ) as spy, mock.patch.object(
            stock_names,
            "_lookup_name_online",
            side_effect=AssertionError("cold load 禁止外网补名"),
        ):
            t0 = time.perf_counter()
            data = index.load_holdings()
            elapsed = time.perf_counter() - t0
        self.assertEqual(spy.call_count, 1, "load_holdings 被 watchlist 回调（递归）")
        self.assertLess(elapsed, 5.0)
        self.assertTrue(data["positions"], "应为盯盘宇宙补齐空仓位")
        overlay = [
            w
            for w in index.effective_watchlist(data)
            if w.get("quote_tier") == "overlay"
        ]
        named = [w for w in overlay if str(w.get("name") or "") not in {"", w.get("code")}]
        self.assertTrue(named, "叠加池应带 picks 本地名称")


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


class TestManualStartupSafety(unittest.TestCase):
    def test_legacy_minute_quote_entry_is_blocked_before_provider_io(self):
        with mock.patch.object(index, "_CONDITION_BUY_ACTIVE", True), \
             mock.patch.object(index, "pull_akshare_1m") as minute, \
             mock.patch.object(index, "fetch_sina_spot") as spot:
            with self.assertRaises(RuntimeError):
                index.fetch_today_quote("sz000070")
            minute.assert_not_called()
            spot.assert_not_called()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pid = Path(self.temp.name) / "watch.pid"
        for item in (mock.patch.object(index,"WATCH_PID_FILE",self.pid),
                     mock.patch("watch_process.PID_FILE",self.pid)):
            item.start()
            self.addCleanup(item.stop)

    def test_unknown_port_is_refused_without_reclaiming(self):
        with mock.patch("watch_process.describe_listeners",return_value={8765:[999]}), \
             mock.patch.object(index.os,"killpg") as kill:
            with self.assertRaises(SystemExit):
                index._acquire_watch_lock(host="127.0.0.1",port=8765)
        self.assertFalse(self.pid.exists())
        kill.assert_not_called()

    def test_live_pid_lock_is_not_overwritten_or_removed(self):
        original='{"pid":999,"port":8765}'
        self.pid.write_text(original)
        with mock.patch("watch_process.pid_alive",return_value=True):
            with self.assertRaises(SystemExit):
                index._acquire_watch_lock(host="127.0.0.1",port=8765)
        self.assertEqual(self.pid.read_text(),original)

    def test_registration_and_release_use_only_own_pid(self):
        with mock.patch("watch_process.describe_listeners",return_value={}):
            index._acquire_watch_lock(host="127.0.0.1",port=8765)
        self.assertEqual(json.loads(self.pid.read_text())["pid"],os.getpid())
        index._release_watch_lock()
        self.assertFalse(self.pid.exists())

    def test_legacy_force_and_embedded_frontend_flags_are_rejected(self):
        parser=index.build_parser()
        for flag in ("--force","--ui-dev","--ui-static","--ui-dev-port"):
            with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
                parser.parse_args(["watch",flag])
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            parser.parse_args(["watch-stop"])
        self.assertEqual(parser.parse_args(["watch","--no-ui-dev"]).func,index.cmd_watch)

    def test_concurrent_manual_starts_register_only_one_writer(self):
        barrier=threading.Barrier(2)
        results=[]
        real_pid=os.getpid()
        def identity():
            return {"starter-a":1001,"starter-b":1002}.get(threading.current_thread().name,real_pid)
        def start():
            barrier.wait()
            try:
                index._acquire_watch_lock(host="127.0.0.1",port=8765)
                results.append("started")
            except SystemExit:
                results.append("refused")
        with mock.patch.object(index.os,"getpid",side_effect=identity), \
             mock.patch("watch_process.pid_alive",return_value=True), \
             mock.patch("watch_process.describe_listeners",return_value={}):
            threads=[threading.Thread(target=start,name=name) for name in ("starter-a","starter-b")]
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=5)
        self.assertEqual(sorted(results),["refused","started"])


if __name__ == "__main__":
    unittest.main()
